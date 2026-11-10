"""Servidor local que recebe os dados do userscript (aba do jogo) e grava no banco.

Uso:
    python src/coletor.py            # escuta em http://127.0.0.1:8765

Rotas:
    GET  /                          status em HTML
    GET  /status                    status em JSON
    GET  /pokeidle-coletor.user.js  o userscript (abrir no navegador com o Tampermonkey instala)
    GET  /vez?nick=X                diz à aba o que fazer agora (exportar / vitrine / itens)
    POST /vendas                    resposta do export (csv.pedir)
    POST /recusa                    export recusado pelo jogo (espera)
    POST /falha                     export sem resposta
    POST /vitrine                   snapshot de market.itens
    POST /itens                     items.json do jogo

O servidor é quem decide a vez, então com várias contas abertas só uma exporta por hora
(o limite do jogo é 1 export por hora; aqui ninguém tenta burlar isso).
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importer  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
USERSCRIPT = Path(__file__).resolve().parent / "userscript" / "pokeidle-coletor.user.js"

ESPERA_PADRAO_MS = 60 * 60_000   # se o jogo não disser quanto falta
MARGEM_MS = 30_000               # folga depois do horário liberado
TRAVA_MS = 90_000                # uma aba pediu; as outras esperam a resposta
VITRINE_A_CADA_MS = 60_000      # a cada minuto: é um pedido leve, e o menor anúncio muda rápido
VITRINE_DETALHE_MS = 3 * 24 * 60 * 60_000   # retratos de minuto em minuto ficam 3 dias...
VITRINE_RESUMO_MS = 15 * 60_000             # ...depois sobra um a cada 15 min (o histórico de antes)
ITENS_A_CADA_MS = 24 * 60 * 60_000

LOCK = threading.Lock()


def agora_ms() -> int:
    return int(time.time() * 1000)


def get(con, chave, padrao=0) -> int:
    r = con.execute("SELECT valor FROM coleta WHERE chave = ?", (chave,)).fetchone()
    return int(r[0]) if r and r[0] is not None else padrao


def put(con, **kv) -> None:
    con.executemany("INSERT INTO coleta (chave, valor) VALUES (?, ?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    [(k, str(v)) for k, v in kv.items()])
    con.commit()


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- ações

def decidir_vez(con, nick: str, diag: dict | None = None) -> dict:
    t = agora_ms()
    diag = diag or {}
    antes = con.execute("SELECT valor FROM coleta WHERE chave = ?", (f"diag:{nick}",)).fetchone()
    if not antes or json.loads(antes[0] or "{}").get("sock") != diag.get("sock"):
        log(f"aba {nick}: socket {'ok' if diag.get('sock') == '1' else 'ainda não'} "
            f"(script v{diag.get('v', '?')}, página {diag.get('pag', '?')})")
    put(con, **{f"visto:{nick}": t,
                f"diag:{nick}": json.dumps(diag, ensure_ascii=False)})
    vez = {"exportar": False, "vitrine": False, "itens": False}
    if diag.get("sock") != "1":  # aba ainda sem o socket do jogo: só registra o contato
        return vez
    if t >= get(con, "export_liberado_em") and t >= get(con, "export_trava_ate"):
        vez["exportar"] = True
        put(con, export_trava_ate=t + TRAVA_MS, export_por=nick)
    if t - get(con, "vitrine_em") >= VITRINE_A_CADA_MS and t >= get(con, "vitrine_trava_ate"):
        vez["vitrine"] = True
        put(con, vitrine_trava_ate=t + TRAVA_MS)
    if t - get(con, "itens_em") >= ITENS_A_CADA_MS and t >= get(con, "itens_trava_ate"):
        vez["itens"] = True
        put(con, itens_trava_ate=t + TRAVA_MS)
    return vez


def receber_vendas(con, body: dict) -> dict:
    linhas = body.get("linhas") or []
    rows = [importer.parse_json_row(r) for r in linhas]
    fonte = f"coletor:{body.get('nick', '?')}:{datetime.now():%Y-%m-%d %H:%M}"
    res = importer.import_rows(con, rows, fonte)
    espera = int(body.get("esperaMs") or ESPERA_PADRAO_MS)
    put(con, export_liberado_em=agora_ms() + espera + MARGEM_MS, export_trava_ate=0,
        ultimo_export_em=agora_ms())
    aviso = "  ⚠ buraco desde o export anterior" if res["gap_before"] else ""
    log(f"export de {body.get('nick')}: {res['rows_in_file']} linhas "
        f"({res.get('oldest')} → {res.get('newest')}), {res['rows_added']:+d} no banco{aviso}")
    return res


def receber_recusa(con, body: dict) -> dict:
    resta = int(body.get("restaMs") or ESPERA_PADRAO_MS)
    put(con, export_liberado_em=agora_ms() + resta + MARGEM_MS, export_trava_ate=0)
    log(f"export recusado ({body.get('chave')}), próximo em {resta // 60000} min")
    return {"ok": True}


def receber_falha(con, body: dict) -> dict:
    # Sem resposta: tenta de novo daqui a 5 min (a hora pode ou não ter sido gasta no servidor).
    put(con, export_trava_ate=agora_ms() + 5 * 60_000)
    log(f"export sem resposta ({body.get('motivo')})")
    return {"ok": True}


def receber_vitrine(con, body: dict) -> dict:
    t = agora_ms()
    ts = datetime.fromtimestamp(t / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
    resumo = body.get("resumo") or {}
    medias = body.get("medias") or {}
    linhas = []
    for item_id in set(resumo) | set(medias):
        r = resumo.get(item_id) or {}
        m = medias.get(item_id) or {}
        g, o = m.get("gold") or {}, m.get("orb") or {}
        linhas.append((t, ts, int(item_id), r.get("anuncios"), r.get("unidades"),
                       r.get("minGold"), r.get("minOrb"),
                       g.get("media"), g.get("unidades"), o.get("media"), o.get("unidades")))
    with con:
        con.executemany("INSERT OR REPLACE INTO vitrine VALUES (?,?,?,?,?,?,?,?,?,?,?)", linhas)
    antes = get(con, "vitrine_em")
    put(con, vitrine_em=t, vitrine_trava_ate=0)
    if t // VITRINE_RESUMO_MS != antes // VITRINE_RESUMO_MS:  # no log, uma linha a cada 15 min basta
        log(f"vitrine: {len(linhas)} itens")
    return {"ok": True, "itens": len(linhas)}


def podar_vitrine(con) -> int:
    """Retratos com mais de 3 dias ficam só um a cada 15 min (o primeiro de cada faixa).
    Sem isso, a vitrine de minuto em minuto cresceria ~50 mil linhas por dia para sempre."""
    corte = agora_ms() - VITRINE_DETALHE_MS
    with con:
        n = con.execute(f"""DELETE FROM vitrine WHERE snap_ms < ? AND snap_ms NOT IN (
                               SELECT MIN(snap_ms) FROM vitrine WHERE snap_ms < ? GROUP BY snap_ms / {VITRINE_RESUMO_MS})""",
                        (corte, corte)).rowcount
    return n


def receber_itens(con, body: dict) -> dict:
    itens = body.get("items") or []
    with con:
        con.executemany(
            "INSERT INTO itens (id, nome, categoria, icone) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET icone = excluded.icone, "
            "nome = CASE WHEN itens.categoria = 'especial' THEN itens.nome ELSE excluded.nome END, "
            "categoria = CASE WHEN itens.categoria = 'especial' THEN itens.categoria ELSE excluded.categoria END",
            [(int(i["id"]), i["name"], i.get("category"), i.get("icon"))
             for i in itens if "id" in i and "name" in i])
    put(con, itens_em=agora_ms(), itens_trava_ate=0)
    log(f"itens: {len(itens)} nomes")
    return {"ok": True}


def status(con) -> dict:
    t = agora_ms()
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    liberado = get(con, "export_liberado_em")
    diags = {r[0][5:]: json.loads(r[1] or "{}")
             for r in con.execute("SELECT chave, valor FROM coleta WHERE chave LIKE 'diag:%'")}
    abas = {}
    for chave, valor in con.execute("SELECT chave, valor FROM coleta WHERE chave LIKE 'visto:%'"):
        n = chave[6:]
        d = diags.get(n, {})
        abas[n] = (f"há {round((t - int(valor)) / 1000)} s · socket {'ok' if d.get('sock') == '1' else 'NÃO'}"
                   f" · v{d.get('v', '?')} · {d.get('pag', '?')}")
    return {
        "vendas_no_banco": q("SELECT COUNT(*) FROM trades"),
        "venda_mais_recente": q("SELECT MAX(ts) FROM trades"),
        "ultimo_export": _hora(get(con, "ultimo_export_em")),
        "proximo_export": _hora(liberado) if liberado > t else "agora",
        "ultima_vitrine": _hora(get(con, "vitrine_em")),
        "snapshots_vitrine": q("SELECT COUNT(DISTINCT snap_ms) FROM vitrine"),
        "buracos": q("SELECT COUNT(*) FROM imports WHERE gap_before = 1"),
        "abas": abas,
    }


def _hora(ms: int) -> str | None:
    return datetime.fromtimestamp(ms / 1000, importer.BRT).strftime("%d/%m %H:%M") if ms else None


# ---------------------------------------------------------------- HTTP

ROTAS_POST = {"/vendas": receber_vendas, "/recusa": receber_recusa, "/falha": receber_falha,
              "/vitrine": receber_vitrine, "/itens": receber_itens}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencia o log padrão por requisição
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path not in ("/status", "/vez"):
            log(f"GET {url.path}")
        if url.path == "/pokeidle-coletor.user.js":
            return self._send(200, USERSCRIPT.read_bytes(), "text/javascript; charset=utf-8")
        with LOCK:
            con = importer.connect()
            try:
                if url.path == "/vez":
                    qs = {k: v[0][:80] for k, v in parse_qs(url.query).items()}
                    nick = qs.pop("nick", "?")[:40]
                    # Versões antigas do script não mandam `sock`; elas só chamam com o socket pronto.
                    qs.setdefault("sock", "1")
                    return self._json(decidir_vez(con, nick, qs))
                st = status(con)
            finally:
                con.close()
        if url.path == "/status":
            return self._json(st)
        if url.path == "/":
            linhas = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in st.items())
            html = (f"<!doctype html><meta charset=utf-8><title>Coletor PokeIdle</title>"
                    f"<meta http-equiv=refresh content=30><body style='font-family:sans-serif'>"
                    f"<h2>Coletor PokeIdle</h2><table cellpadding=6>{linhas}</table>"
                    f"<p><a href='/pokeidle-coletor.user.js'>Instalar/atualizar userscript</a></p>")
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        self._json({"erro": "rota desconhecida"}, 404)

    def do_POST(self):
        fn = ROTAS_POST.get(urlparse(self.path).path)
        if not fn:
            return self._json({"erro": "rota desconhecida"}, 404)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            return self._json({"erro": "json inválido"}, 400)
        with LOCK:
            con = importer.connect()
            try:
                return self._json(fn(con, body))
            except Exception as e:  # não derruba o servidor por uma resposta torta
                log(f"erro em {self.path}: {e!r}")
                return self._json({"erro": repr(e)}, 500)
            finally:
                con.close()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"coletor ouvindo em http://{HOST}:{PORT}  (Ctrl+C para parar)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
