"""Painel web do mercado (lê data/market.db).

    python src/painel.py      # abre em http://127.0.0.1:8770

Só escuta no próprio PC.
"""
from __future__ import annotations

import json
import mimetypes
import statistics
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import notificar  # noqa: E402
from analise import pokemon as analise_pokemon  # noqa: E402
from analise import caca, evolucao, pvp, sinais, venda  # noqa: E402
from coleta import coletor, importer  # noqa: E402

HOST, PORT = "127.0.0.1", 8770
WEB = caminhos.WEB

TAXA_ITEM = 0.15
USD_POR_GEMA = 0.009          # recompra (saque) oficial
FATOR_OUTLIER = 4.0           # fora de [mediana/4, mediana×4] = venda suspeita
HORA = 3600_000
DIA = 24 * HORA
JANELAS = {"24h": DIA, "7d": 7 * DIA, "30d": 30 * DIA, "tudo": None}

RARIDADES = [("Comum", "Common", 0.745), ("Incomum", "Uncommon", 0.20), ("Rara", "Rare", 0.05),
             ("Mítica", "Mythic", 0.005), ("Lendária", "Legendary", 0.00005)]
MONTAGENS = {"casa": ("Key Fragment", "House"), "bicicleta": ("Bicycle Fragment", "Bicycle")}


# ---------------------------------------------------------------- utilidades

def agora_ms() -> int:
    return int(time.time() * 1000)


def ts_de_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")


_cache_ts: dict[str, int] = {}


def ms_da_linha(ts: str, ts_ms: int | None) -> int:
    """Horário exato quando existe (coletor); senão o meio do minuto do CSV."""
    if ts_ms:
        return int(ts_ms)
    v = _cache_ts.get(ts)
    if v is None:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=importer.BRT)
        v = _cache_ts[ts] = int(dt.timestamp() * 1000) + 30_000
    return v


def mediana(v):
    return statistics.median(v) if v else None


def percentil(v_ordenado, p):
    if not v_ordenado:
        return None
    k = (len(v_ordenado) - 1) * p
    i = int(k)
    j = min(i + 1, len(v_ordenado) - 1)
    return v_ordenado[i] + (v_ordenado[j] - v_ordenado[i]) * (k - i)


def separar_outliers(precos):
    """(normais, suspeitos) pelo fator em torno da mediana."""
    m = mediana(precos)
    if not m:
        return precos, []
    lo, hi = m / FATOR_OUTLIER, m * FATOR_OUTLIER
    return [p for p in precos if lo <= p <= hi], [p for p in precos if not lo <= p <= hi]


def variacao(atual, antes):
    if atual is None or not antes:
        return None
    return round((atual / antes - 1) * 100, 1)


CATEGORIAS = ["casas", "bicicletas", "fragmentos", "pedras", "boss-tokens", "tickets", "tms", "outros"]

# Ícones do próprio jogo, carregados direto de pokeidle.io pelo navegador (nada é copiado para cá).
SITE = "https://pokeidle.io"
ICONE_GENERICO = f"{SITE}/assets/site/assets/ui/menu-bolsa.png"
_RAR_ARQ = {"Common": "comum", "Uncommon": "incomum", "Rare": "rara", "Mythic": "mitica", "Legendary": "lendaria"}
ICONES_POR_NOME = {
    "Key Fragment": "/img/itens/fragmento-chave.png",
    "Bicycle Fragment": "/img/itens/fragmento-bicicleta.png",
    "Shiny Stone Fragment": "/img/itens/shiny-stone.png",       # o jogo não tem arte separada do fragmento
    "Mega Stone Fragment": "/img/itens/fragmento-mega.png",
    "Mega Shiny Stone Fragment": "/img/itens/fragmento-mega-shiny.png",
    "Shiny Egg Fragment": "/img/itens/fragmento-ovo-shiny.png",
    "Fragmento de Z-Move": "/img/itens/zmove/fragmento.png",
    "AoE TM Disk Piece": "/img/itens/zmove/aoe-peca.png",
    "Safari Ticket": "/img/itens/safari-ticket.png",
    "Mystic Ticket": "/img/itens/mystic-ticket.png",
    **{f"{en} House": f"/img/itens/casa-{pt}.png" for en, pt in _RAR_ARQ.items()},
    **{f"{en} Bicycle": f"/img/itens/bicicleta-{pt}.png" for en, pt in _RAR_ARQ.items()},
}


def caminho_icone_rel(icon: str | None) -> str | None:
    """Mesma regra do jogo (shared/icone-item.mjs): campo `icon` → caminho em /assets/."""
    if not icon:
        return None
    if icon.startswith("site/"):
        return icon
    if icon.startswith("/"):
        return f"site{icon}"
    return f"site/assets/items/{icon}"


def mapa_icones(con) -> dict[str, str]:
    mapa = {}
    for r in con.execute("SELECT nome, icone FROM itens WHERE icone IS NOT NULL"):
        rel = caminho_icone_rel(r["icone"])
        if rel:
            mapa[r["nome"]] = f"{SITE}/assets/{rel}"
    mapa.update({n: SITE + p for n, p in ICONES_POR_NOME.items()})
    return mapa


def categoria(nome: str) -> str:
    """Mesmas categorias do mercado do jogo (mais TMs e Outros para o que sobra)."""
    n = nome.lower()
    if "fragment" in n:  # antes de casa/bike/pedra: "Bicycle Fragment", "Shiny Stone Fragment"
        return "fragmentos"
    if "house" in n:
        return "casas"
    if "bicycle" in n:
        return "bicicletas"
    if "token" in n:
        return "boss-tokens"
    if "ticket" in n:
        return "tickets"
    if "tm " in n or "disk" in n:
        return "tms"
    if "stone" in n:
        return "pedras"
    return "outros"


# ---------------------------------------------------------------- consultas

def vitrine_atual(con) -> dict[str, dict]:
    snap = con.execute("SELECT MAX(snap_ms) FROM vitrine").fetchone()[0]
    if not snap:
        return {}
    out = {}
    for r in con.execute("""SELECT v.*, COALESCE(i.nome, 'Item #' || v.item_id) AS nome
                            FROM vitrine v LEFT JOIN itens i ON i.id = v.item_id WHERE v.snap_ms = ?""", (snap,)):
        out[r["nome"]] = {"id": r["item_id"], "anuncios": r["anuncios"], "unidades": r["unidades"],
                          "min": {"gems": r["min_gems"], "coins": r["min_coins"]},
                          "media7": {"gems": r["media7_gems"], "coins": r["media7_coins"]},
                          "un7": {"gems": r["un7_gems"], "coins": r["un7_coins"]},
                          "snap_ms": snap}
    return out


def api_resumo(con, moeda: str) -> dict:
    t = agora_ms()
    inicio = ts_de_ms(t - 8 * DIA)
    por_item: dict[str, list] = defaultdict(list)
    for r in con.execute("""SELECT base_name, ts, ts_ms, unit_price, qty FROM trades
                            WHERE kind = 'item' AND currency = ? AND ts >= ?""", (moeda, inicio)):
        por_item[r["base_name"]].append((ms_da_linha(r["ts"], r["ts_ms"]), r["unit_price"], r["qty"]))
    ultimos = {r["base_name"]: (r["ts"], r["n"]) for r in con.execute(
        "SELECT base_name, MAX(ts) AS ts, COUNT(*) AS n FROM trades WHERE kind='item' AND currency=? GROUP BY 1",
        (moeda,))}
    vit = vitrine_atual(con)
    icones = mapa_icones(con)
    nomes = set(por_item) | set(ultimos) | {n for n, v in vit.items() if v["min"][moeda] or v["media7"][moeda]}

    itens = []
    for nome in nomes:
        linhas = por_item.get(nome, [])
        def janela(de, ate):
            ps = [p for (ms, p, _) in linhas if t - de <= ms < t - ate]
            return separar_outliers(ps)[0]
        p24 = janela(DIA, 0)
        atual, poucas = mediana(p24), False
        if len(p24) < 3:  # pouco volume: mediana das últimas 10 vendas de qualquer momento
            ult = [r[0] for r in con.execute(
                "SELECT unit_price FROM trades WHERE kind='item' AND currency=? AND base_name=? "
                "ORDER BY ts DESC LIMIT 10", (moeda, nome))]
            atual, poucas = mediana(separar_outliers(ult)[0]), True
        # Mini gráfico: mediana a cada 6 h nos últimos 7 dias.
        faixas = [[] for _ in range(28)]
        for ms, p, _ in linhas:
            k = int((t - ms) // (6 * HORA))
            if 0 <= k < 28:
                faixas[27 - k].append(p)
        spark = [mediana(separar_outliers(f)[0]) if f else None for f in faixas]
        v = vit.get(nome, {})
        itens.append({
            "nome": nome, "icone": icones.get(nome, ICONE_GENERICO), "categoria": categoria(nome),
            "atual": atual, "poucas_vendas": poucas,
            "var24h": variacao(mediana(p24), mediana(janela(2 * DIA, DIA))),
            "var7d": variacao(mediana(p24), mediana(janela(7 * DIA, 6 * DIA))),
            "vendas24h": len([1 for (ms, _, _) in linhas if ms >= t - DIA]),
            "unidades24h": sum(q for (ms, _, q) in linhas if ms >= t - DIA),
            "ultima_venda": ultimos.get(nome, (None, 0))[0],
            "vendas_total": ultimos.get(nome, (None, 0))[1],
            "anuncio_min": (v.get("min") or {}).get(moeda),
            "anuncios": v.get("anuncios"),
            "media7_jogo": (v.get("media7") or {}).get(moeda),
            "spark": spark,
        })
    itens.sort(key=lambda i: (-(i["vendas24h"]), i["nome"]))
    return {"moeda": moeda, "itens": itens, "agora": t}


PASSOS_GRAFICO = (5 * 60_000, 10 * 60_000, 15 * 60_000, 30 * 60_000, HORA, 3 * HORA, 6 * HORA, 12 * HORA, DIA, 7 * DIA)
MAX_BALDES = 120
ZOOM_MINIMO = HORA  # o zoom não fica menor que 1 h (com baldes de 5 min, são 12 pontos)


def _vendas_janela(con, nome: str, moeda: str, dur, t: int):
    """Vendas do item na janela e o filtro de suspeitas (pela mediana da janela inteira)."""
    filtro, args = "kind='item' AND currency=? AND base_name=?", [moeda, nome]
    if dur:
        filtro += " AND ts >= ?"
        args.append(ts_de_ms(t - dur))
    linhas = [(ms_da_linha(r["ts"], r["ts_ms"]), r) for r in con.execute(
        f"SELECT * FROM trades WHERE {filtro} ORDER BY ts", args)]
    m_janela = mediana([r["unit_price"] for _, r in linhas])
    lo, hi = (m_janela / FATOR_OUTLIER, m_janela * FATOR_OUTLIER) if m_janela else (0, float("inf"))
    return linhas, (lambda p: lo <= p <= hi)


def _baldes(bons, ini: int, fim: int):
    """Agrupa as vendas de [ini, fim] em até MAX_BALDES baldes.

    Os baldes começam em horas redondas do horário de Brasília (14:00–14:15, não 14:07–14:22),
    para o tooltip e o eixo baterem com o relógio."""
    span = max(fim - ini, 1)
    passo = next((p for p in PASSOS_GRAFICO if span / p <= MAX_BALDES), PASSOS_GRAFICO[-1])
    desloc = int(importer.BRT.utcoffset(None).total_seconds() * 1000)  # -3 h
    baldes: dict[int, list] = defaultdict(list)
    for ms, r in bons:
        if ini <= ms <= fim:
            baldes[(ms + desloc) // passo].append(r)
    serie = []
    for k in sorted(baldes):
        rs = baldes[k]
        ps = [r["unit_price"] for r in rs]
        t0 = k * passo - desloc
        serie.append({"t": t0, "fim": t0 + passo, "mediana": mediana(ps),
                      "min": min(ps), "max": max(ps), "vendas": len(rs), "unidades": sum(r["qty"] for r in rs)})
    return passo, serie


def _anuncios(con, nome: str, moeda: str, de, ate=None, passo=None):
    """Menor anúncio da vitrine em cada foto, de `de` até `ate` (ms), reduzido ao ritmo dos baldes."""
    vit_id = con.execute("SELECT id FROM itens WHERE nome = ?", (nome,)).fetchone()
    if not vit_id:
        return []
    col = "min_gems" if moeda == "gems" else "min_coins"
    q = f"SELECT snap_ms, {col} AS v, anuncios FROM vitrine WHERE item_id = ?"
    args = [vit_id[0]]
    if de:
        q += " AND snap_ms >= ?"
        args.append(de)
    if ate:
        q += " AND snap_ms <= ?"
        args.append(ate)
    fotos = [{"t": r["snap_ms"], "min": r["v"], "anuncios": r["anuncios"]}
             for r in con.execute(q + " ORDER BY snap_ms", args)]
    if not passo or len(fotos) <= 2 * MAX_BALDES:
        return fotos
    # Muitas fotos (a vitrine é lida a cada poucos minutos): uma por meio balde, a de valor mediano.
    # É sempre uma foto real (o tooltip mostra o horário dela) e não puxa a linha para os extremos.
    meio = max(passo // 2, 1)
    desloc = int(importer.BRT.utcoffset(None).total_seconds() * 1000)
    grupos: dict[int, list] = defaultdict(list)
    for f in fotos:
        grupos[(f["t"] + desloc) // meio].append(f)
    out = []
    for k in sorted(grupos):
        g = grupos[k]
        com = sorted((f for f in g if f["min"] is not None), key=lambda f: f["min"])
        out.append(com[(len(com) - 1) // 2] if com else g[-1])
    return out


def api_item(con, nome: str, moeda: str, janela: str) -> dict:
    t = agora_ms()
    dur = JANELAS.get(janela, 7 * DIA)
    linhas, normal = _vendas_janela(con, nome, moeda, dur, t)
    bons = [(ms, r) for ms, r in linhas if normal(r["unit_price"])]
    pb = sorted(r["unit_price"] for _, r in bons)
    unidades = sum(r["qty"] for _, r in bons)

    # Baldes do gráfico: tamanho pela janela (ou pelo intervalo de dados em "tudo").
    # O eixo começa onde os dados começam (a coleta é recente), com uma folga de 4%.
    ini = (t - dur) if dur else (linhas[0][0] if linhas else t - DIA)
    if linhas and linhas[0][0] > ini:
        ini = max(ini, linhas[0][0] - (t - linhas[0][0]) * 0.04)
    ini = int(ini)
    passo, serie = _baldes(bons, ini, max(t, ini + HORA))
    anuncios = _anuncios(con, nome, moeda, (t - dur) if dur else None, passo=passo)
    vit = vitrine_atual(con).get(nome, {})

    recentes = [{"t": ms, "qtd": r["qty"], "unit": r["unit_price"], "total": r["total"],
                 "vendedor": r["seller"], "comprador": r["buyer"], "suspeita": not normal(r["unit_price"]),
                 "exato": bool(r["ts_ms"])}
                for ms, r in reversed(linhas[-60:])]
    return {
        "nome": nome, "icone": mapa_icones(con).get(nome, ICONE_GENERICO), "moeda": moeda, "janela": janela, "agora": t,
        "inicio": ini, "passo": passo,
        "stats": {
            "vendas": len(bons), "unidades": unidades, "suspeitas": len(linhas) - len(bons),
            "mediana": mediana(pb), "media": (sum(r["total"] for _, r in bons) / unidades) if unidades else None,
            "min": pb[0] if pb else None, "max": pb[-1] if pb else None,
            "p10": percentil(pb, 0.1), "p90": percentil(pb, 0.9),
            "primeira": bons[0][0] if bons else None, "ultima": bons[-1][0] if bons else None,
        },
        "serie": serie, "anuncios": anuncios,
        "vitrine": {"min": (vit.get("min") or {}).get(moeda), "anuncios": vit.get("anuncios"),
                    "unidades": vit.get("unidades"), "media7": (vit.get("media7") or {}).get(moeda),
                    "snap_ms": vit.get("snap_ms")},
        "recentes": recentes,
        "taxa": TAXA_ITEM, "usd_por_gema": USD_POR_GEMA,
    }


def api_item_serie(con, nome: str, moeda: str, janela: str, de: int, ate: int) -> dict:
    """Zoom do gráfico: a série de [de, ate] com baldes mais finos e o resumo do trecho.

    As suspeitas seguem a mediana da janela inteira, para o zoom bater com o gráfico de fora."""
    t = agora_ms()
    ate = min(ate or t, t)
    de = min(de, ate - ZOOM_MINIMO)
    linhas, normal = _vendas_janela(con, nome, moeda, JANELAS.get(janela, 7 * DIA), t)
    bons = [(ms, r) for ms, r in linhas if normal(r["unit_price"]) and de <= ms <= ate]
    passo, serie = _baldes(bons, de, ate)
    pb = sorted(r["unit_price"] for _, r in bons)
    return {
        "nome": nome, "moeda": moeda, "de": de, "ate": ate, "passo": passo,
        "serie": serie, "anuncios": _anuncios(con, nome, moeda, de, ate, passo),
        "resumo": {"vendas": len(bons), "unidades": sum(r["qty"] for _, r in bons), "mediana": mediana(pb),
                   "min": pb[0] if pb else None, "max": pb[-1] if pb else None},
    }


def api_montagem(con) -> dict:
    t = agora_ms()
    desde = ts_de_ms(t - 7 * DIA)
    vit = vitrine_atual(con)

    def preco_vendas(nome):
        ps = [r[0] for r in con.execute(
            "SELECT unit_price FROM trades WHERE kind='item' AND currency='gems' AND base_name=? AND ts>=?",
            (nome, desde))]
        ps = separar_outliers(ps)[0]
        return mediana(ps), len(ps)

    out = {}
    for chave, (frag, sufixo) in MONTAGENS.items():
        fm, fn = preco_vendas(frag)
        fa = (vit.get(frag) or {}).get("min", {}).get("gems")
        fj = (vit.get(frag) or {}).get("media7", {}).get("gems")
        linhas = []
        for pt, en, chance in RARIDADES:
            nome = f"{en} {sufixo}"
            m, n = preco_vendas(nome)
            v = vit.get(nome) or {}
            linhas.append({"raridade": pt, "nome": nome, "chance": chance, "mediana": m, "vendas": n,
                           "icone": SITE + ICONES_POR_NOME[nome],
                           "anuncio": (v.get("min") or {}).get("gems"), "anuncios": v.get("anuncios"),
                           "media7_jogo": (v.get("media7") or {}).get("gems")})
        out[chave] = {"fragmento": frag, "frag_mediana": fm, "frag_vendas": fn, "frag_anuncio": fa,
                      "frag_media7_jogo": fj, "frag_icone": SITE + ICONES_POR_NOME[frag],
                      "icone": SITE + ICONES_POR_NOME[f"Common {sufixo}"],
                      "linhas": linhas}
    return {"montagens": out, "taxa": TAXA_ITEM, "usd_por_gema": USD_POR_GEMA, "agora": t}


def api_pokemon(con, busca: str, moeda: str, shiny: bool, limite: int) -> dict:
    filtro, args = ["kind='pokemon'"], []
    if moeda in ("gems", "coins"):
        filtro.append("currency=?")
        args.append(moeda)
    if busca:
        filtro.append("base_name LIKE ?")
        args.append(f"%{busca}%")
    if shiny:
        filtro.append("shiny=1")
    rows = con.execute(f"SELECT * FROM trades WHERE {' AND '.join(filtro)} ORDER BY ts DESC, ts_ms DESC LIMIT ?",
                       args + [limite]).fetchall()
    return {"vendas": [{"t": ms_da_linha(r["ts"], r["ts_ms"]), "especie": r["base_name"], "nivel": r["level"],
                        "shiny": bool(r["shiny"]), "iv": r["iv_total"], "potencia": r["potencia"],
                        "qualidade": r["qualidade"], "nota": r["nota"], "preco": r["total"],
                        "moeda": r["currency"], "vendedor": r["seller"], "comprador": r["buyer"]} for r in rows]}


def api_sinais(con, moeda: str) -> dict:
    sinais.preparar(con)
    icones = mapa_icones(con)
    itens = sinais.calcular(con, moeda)
    for s in itens:
        s["icone"] = icones.get(s["nome"], ICONE_GENERICO)
        s["categoria"] = categoria(s["nome"])
    nomes = sorted({r[0] for r in con.execute("SELECT DISTINCT base_name FROM trades WHERE kind='item'")}
                   | {s["nome"] for s in itens})
    return {"moeda": moeda, "itens": itens, "regras": sinais.regras(con), "log": sinais.log(con, 40),
            "tipos": sinais.TIPOS_REGRA, "canais": notificar.canais_ativos(), "nomes": nomes,
            "taxa": sinais.TAXA, "min_vendas_ref": sinais.MIN_VENDAS_REF}


def api_venda(con, nome: str, qtd: int) -> dict:
    """Vender o que dropou: moeda, preço e momento (src/venda.py)."""
    if not nome:
        raise ValueError("falta o nome do item")
    d = venda.analisar(con, nome, qtd, MONTAGENS, RARIDADES)
    d["icone"] = mapa_icones(con).get(nome, ICONE_GENERICO)
    return d


def api_alertas_novos(con, desde_ms: int) -> dict:
    """Para o aviso sonoro da página: os alertas gravados pelo robô depois do horário `desde_ms`.
    (Pelo horário e não pelo id: o SQLite pode reaproveitar ids de linhas apagadas.)"""
    sinais.preparar(con)
    ultimo = con.execute("SELECT COALESCE(MAX(ms), 0) FROM alertas_log").fetchone()[0]
    novos = [] if desde_ms < 0 else [dict(r) for r in con.execute(
        "SELECT id, regra_id, item, moeda, valor, msg, ms FROM alertas_log WHERE ms > ? ORDER BY ms LIMIT 20", (desde_ms,))]
    return {"ultimo": max(ultimo, desde_ms), "novos": novos}


def post_regra(con, b: dict) -> dict:
    sinais.preparar(con)
    tipo = b.get("tipo")
    if tipo not in sinais.TIPOS_REGRA:
        raise ValueError("tipo de regra inválido")
    valor = float(b.get("valor"))
    moeda = b.get("moeda") if b.get("moeda") in ("gems", "coins") else "gems"
    item = (b.get("item") or "").strip()[:80] or None
    con.execute("INSERT INTO alertas_regras (tipo, item, moeda, valor, criado_ms) VALUES (?,?,?,?,?)",
                (tipo, item, moeda, valor, agora_ms()))
    con.commit()
    return {"ok": True}


def post_regra_acao(con, b: dict, acao: str) -> dict:
    sinais.preparar(con)
    rid = int(b.get("id"))
    if acao == "apagar":
        con.execute("DELETE FROM alertas_regras WHERE id = ?", (rid,))
    else:
        con.execute("UPDATE alertas_regras SET ativo = 1 - ativo WHERE id = ?", (rid,))
    con.commit()
    return {"ok": True}


def post_testar(con, b: dict) -> dict:
    ok, erros = notificar.enviar("PokeIdle Tracker", "Teste de alerta: se você está lendo isto, as notificações funcionam.")
    return {"ok": bool(ok) and not erros, "canais": ok, "erros": erros}


def api_evolucao(con, q: dict) -> dict:
    """Análise de um Pokémon só, com a evolução final: de um anúncio da loja (`anuncio`) ou da ficha digitada."""
    num = lambda k, d=0.0: float(q[k]) if q.get(k, "").strip() else d  # noqa: E731
    m = caca.motor()
    if q.get("anuncio", "").strip():
        ficha = evolucao.ficha_do_anuncio(con, int(num("anuncio")))
    else:
        sid = evolucao.especie_por_nome(m, (q.get("especie_id") or q.get("especie", ""))[:40])
        if not sid:
            raise ValueError("escolha uma espécie da lista")
        if not 1 <= num("nivel") <= 1_000_000:
            raise ValueError("informe o nível do Pokémon")
        ficha = {"species_id": sid, "nivel": int(num("nivel")), "qualidade": num("qualidade", 1.0),
                 "potencia": int(num("potencia", 1)), "shiny": q.get("shiny") == "1",
                 "ivs": {k: int(num(k, 1)) for k in evolucao.STATS}}
        # Da ficha copiada do jogo: os stats reais (já com lendário e refino), a nota e o poder dele.
        stats = {k: int(num("st_" + k)) for k in evolucao.STATS if num("st_" + k) > 0}
        if len(stats) == len(evolucao.STATS):
            ficha["stats"] = stats
        if q.get("nota", "").strip():
            ficha["nota"] = num("nota")
        if q.get("poder", "").strip():
            ficha["poder"] = int(num("poder"))
        if q.get("refino") == "1":
            ficha["refino"] = 1
    alvo = int(num("alvo")) or None
    r = evolucao.analisar(ficha, int(num("treinador")) or None, alvo, analise_pokemon.comparaveis(con), m)
    if not m.tem_evolucoes:
        r["avisos"].insert(0, "o catálogo do jogo ainda não tem a árvore de evolução: o robô baixa"
                              " o catálogo de novo em até 1 dia")
    return r | {"anuncio": ficha.get("anuncio")}


def api_status(con) -> dict:
    st = coletor.status(con)
    st["vendas_com_ms"] = con.execute("SELECT COUNT(*) FROM trades WHERE ts_ms IS NOT NULL").fetchone()[0]
    st["buracos_lista"] = [{"antes_de": r["oldest_ts"], "arquivo": r["file"]} for r in con.execute(
        "SELECT oldest_ts, file FROM imports WHERE gap_before = 1 ORDER BY id DESC LIMIT 5")]
    log = caminhos.LOG_ROBO
    st["robo_log"] = log.read_text(encoding="utf-8", errors="replace").splitlines()[-6:] if log.exists() else []
    return st


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/api/"):
            moeda = q.get("moeda", "gems") if q.get("moeda") in ("gems", "coins") else "gems"
            con = importer.connect()
            try:
                if url.path == "/api/resumo":
                    return self._json(api_resumo(con, moeda))
                if url.path == "/api/item":
                    return self._json(api_item(con, q.get("nome", ""), moeda, q.get("janela", "7d")))
                if url.path == "/api/item/serie":
                    return self._json(api_item_serie(con, q.get("nome", ""), moeda, q.get("janela", "7d"),
                                                     int(float(q.get("de", 0))), int(float(q.get("ate", 0)))))
                if url.path == "/api/montagem":
                    return self._json(api_montagem(con))
                if url.path == "/api/pokemon":
                    return self._json(api_pokemon(con, q.get("busca", "").strip()[:40], q.get("moeda", ""),
                                                  q.get("shiny") == "1", min(int(q.get("limite", 200)), 1000)))
                if url.path == "/api/status":
                    return self._json(api_status(con))
                if url.path == "/api/sinais":
                    return self._json(api_sinais(con, moeda))
                if url.path == "/api/pk/padroes":
                    return self._json(analise_pokemon.padroes(con, moeda, int(q.get("dias", 7))))
                if url.path == "/api/pk/buscar":
                    num = lambda k, d=0: float(q[k]) if q.get(k, "").strip() else d  # noqa: E731
                    objetivo = q.get("objetivo", "equilibrado")
                    pesos, extra = None, {}
                    if objetivo in ("pvp", "ponte"):
                        try:
                            pesos = pvp.pesos_especies(con, q.get("pvp_faixa", "alto")[:12], q.get("pvp_nick", "").strip()[:20])
                        except pvp.ErroPvP as e:
                            if objetivo == "pvp":
                                raise
                            extra["aviso_pvp"] = str(e)  # sem o Tracker a ponte ainda serve (ordena pelo ⚔)
                    if objetivo == "ponte":
                        extra["transferir"] = num("transferir")
                        extra["coins_por_gema"] = venda.cambio(con)["coins_por_gema"]
                    return self._json(analise_pokemon.buscar(
                        con, num("orcamento", 1e18), moeda, objetivo,
                        q.get("especie", "").strip()[:40], q.get("tipo", "")[:12], q.get("shiny") == "1",
                        int(num("pmin")), int(num("nivel")), num("nota"), pesos_pvp=pesos,
                        nivel_treinador=int(num("treinador")) or None, transferir=extra.get("transferir", 0),
                        coins_por_gema=extra.get("coins_por_gema"))
                        | {"objetivos": analise_pokemon.OBJETIVOS, "aviso_pvp": extra.get("aviso_pvp")})
                if url.path == "/api/pk/especies":
                    return self._json({"especies": evolucao.especies()})
                if url.path == "/api/pk/evolucao":
                    return self._json(api_evolucao(con, q))
                if url.path == "/api/pvp":
                    orc = float(q["orcamento"]) if q.get("orcamento", "").strip() else None
                    return self._json(pvp.analisar(con, q.get("nick", "")[:20], q.get("faixa", "")[:12], orc,
                                                   q.get("moeda") if q.get("moeda") in ("gems", "coins") else "gems",
                                                   forcar=q.get("forcar") == "1"))
                if url.path == "/api/venda":
                    return self._json(api_venda(con, q.get("nome", "").strip()[:80], min(max(int(q.get("qtd", 1) or 1), 1), 1_000_000)))
                if url.path == "/api/alertas/novos":
                    return self._json(api_alertas_novos(con, int(q.get("desde", -1))))
                return self._json({"erro": "rota desconhecida"}, 404)
            except (pvp.ErroPvP, ValueError, caca.SemDados) as e:
                return self._json({"erro": str(e)}, 400)
            except Exception as e:
                return self._json({"erro": repr(e)}, 500)
            finally:
                con.close()
        nome = "index.html" if url.path in ("", "/") else url.path.lstrip("/")
        return self._estatico(nome)

    def do_POST(self):
        # Só aceita JSON: um site qualquer não consegue mandar esse tipo para 127.0.0.1 sem a
        # permissão do navegador (CORS), então nenhuma página de fora mexe nas regras.
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._json({"erro": "use application/json"}, 415)
        rotas = {"/api/regras": post_regra,
                 "/api/regras/apagar": lambda c, b: post_regra_acao(c, b, "apagar"),
                 "/api/regras/alternar": lambda c, b: post_regra_acao(c, b, "alternar"),
                 "/api/alertas/testar": post_testar}
        fn = rotas.get(urlparse(self.path).path)
        if not fn:
            return self._json({"erro": "rota desconhecida"}, 404)
        try:
            corpo = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 65536)) or b"{}")
        except json.JSONDecodeError:
            return self._json({"erro": "json inválido"}, 400)
        con = importer.connect()
        try:
            return self._json(fn(con, corpo))
        except (ValueError, TypeError) as e:
            return self._json({"erro": str(e)}, 400)
        finally:
            con.close()

    def _estatico(self, nome: str):
        arq = (WEB / nome).resolve()
        if WEB.resolve() not in arq.parents or not arq.is_file():
            return self._json({"erro": "não encontrado"}, 404)
        ctype = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, arq.read_bytes(), ctype)


class Servidor(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR deixa DOIS processos ouvirem a mesma porta, e o navegador cai ora num,
    # ora no outro. Sem isso, um segundo painel na mesma porta falha na hora, com um aviso claro.
    allow_reuse_address = False


def aquecer() -> None:
    """Em segundo plano, ao ligar: o modelo de preço justo (~3 s) e o motor de caça, para a 1ª busca de
    Pokémon não pagar esse tempo."""
    con = importer.connect()
    try:
        analise_pokemon.comparaveis(con)
        caca.motor()
    except Exception as e:  # noqa: BLE001 - é só para adiantar; a busca faz de novo se precisar
        print(f"aquecimento: {e!r}", flush=True)
    finally:
        con.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    porta = PORT
    if "--porta" in sys.argv:
        porta = int(sys.argv[sys.argv.index("--porta") + 1])
    try:
        srv = Servidor((HOST, porta), Handler)
    except OSError:
        print(f"A porta {porta} já está em uso: o painel provavelmente já está aberto em http://{HOST}:{porta}", flush=True)
        sys.exit(3)  # 3 = não adianta religar (a bandeja respeita isso)
    print(f"Painel em http://{HOST}:{porta}  (Ctrl+C para parar)", flush=True)
    threading.Thread(target=aquecer, name="aquecer", daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
