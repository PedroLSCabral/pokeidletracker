"""Fase 3: sinais de mercado e alertas.

Sinais por item (numa moeda):
  - oportunidade de revenda: comprar no menor anúncio e revender pelo preço de referência, já pagando a taxa
    (anúncio abaixo de referência ÷ 4 fica de fora: é outro mercado, não uma pechincha);
  - barato/caro: mediana das últimas 24 h contra a de 7 dias;
  - liquidez: vendas por dia (pouca venda = difícil revender rápido).

Regras de alerta ficam no banco (`alertas_regras`); o robô chama `avaliar()` depois de cada coleta e
manda o que disparar para `notificar.enviar()`.
"""
from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from datetime import datetime

import importer

TAXA = 0.15
HORA = 3600_000
DIA = 24 * HORA
FATOR_OUTLIER = 4.0
MIN_VENDAS_REF = 10          # menos que isso em 7 dias: sem preço de referência confiável
LIQUIDEZ = [(20, "alta"), (5, "média"), (0, "baixa")]   # vendas por dia
ESPERA_REPETIR_MS = 6 * HORA  # o mesmo alerta não se repete antes disso...
MELHORA_PARA_REPETIR = 0.05   # ...a não ser que o valor melhore 5%

TIPOS_REGRA = {
    "oportunidade": "margem de revenda ≥ X%",
    "abaixo": "menor anúncio ≤ X",
    "acima": "mediana 24h ≥ X",
    "variacao": "variação de 7 dias ≥ X% (para cima ou para baixo)",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS alertas_regras (
    id        INTEGER PRIMARY KEY,
    tipo      TEXT NOT NULL,          -- oportunidade | abaixo | acima | variacao
    item      TEXT,                   -- NULL = qualquer item
    moeda     TEXT NOT NULL DEFAULT 'gems',
    valor     REAL NOT NULL,
    ativo     INTEGER NOT NULL DEFAULT 1,
    criado_ms INTEGER
);
CREATE TABLE IF NOT EXISTS alertas_log (
    id       INTEGER PRIMARY KEY,
    regra_id INTEGER,
    item     TEXT,
    moeda    TEXT,
    valor    REAL,              -- o número que disparou (margem, preço, variação)
    msg      TEXT,
    ms       INTEGER,
    canais   TEXT
);
CREATE INDEX IF NOT EXISTS alertas_log_ms ON alertas_log(ms);
"""


def preparar(con) -> None:
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM alertas_regras LIMIT 1").fetchone():
        # Regra inicial: qualquer item em gemas com 10%+ de margem de revenda.
        con.execute("INSERT INTO alertas_regras (tipo, item, moeda, valor, criado_ms) VALUES ('oportunidade', NULL, 'gems', 10, ?)",
                    (int(time.time() * 1000),))
    con.commit()


def _mediana(v):
    return statistics.median(v) if v else None


def _sem_outliers(v):
    m = _mediana(v)
    if not m:
        return v
    return [p for p in v if m / FATOR_OUTLIER <= p <= m * FATOR_OUTLIER]


def _ms(ts, ts_ms, cache={}):
    if ts_ms:
        return int(ts_ms)
    v = cache.get(ts)
    if v is None:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=importer.BRT)
        v = cache[ts] = int(dt.timestamp() * 1000) + 30_000
    return v


def liquidez(vendas_dia: float) -> str:
    return next(nome for limite, nome in LIQUIDEZ if vendas_dia >= limite)


def calcular(con, moeda: str = "gems") -> list[dict]:
    t = int(time.time() * 1000)
    desde = datetime.fromtimestamp((t - 7 * DIA) / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
    linhas = defaultdict(list)
    for r in con.execute("SELECT base_name, ts, ts_ms, unit_price FROM trades "
                         "WHERE kind='item' AND currency=? AND ts >= ?", (moeda, desde)):
        linhas[r["base_name"]].append((_ms(r["ts"], r["ts_ms"]), r["unit_price"]))

    snap = con.execute("SELECT MAX(snap_ms) FROM vitrine").fetchone()[0]
    col = "min_gems" if moeda == "gems" else "min_coins"
    vit = {}
    if snap:
        for r in con.execute(f"""SELECT COALESCE(i.nome, 'Item #' || v.item_id) AS nome, v.{col} AS mn, v.anuncios, v.unidades
                                 FROM vitrine v LEFT JOIN itens i ON i.id = v.item_id WHERE v.snap_ms = ?""", (snap,)):
            vit[r["nome"]] = r

    out = []
    for nome in set(linhas) | set(vit):
        vs = linhas.get(nome, [])
        p7 = _sem_outliers([p for _, p in vs])
        p24 = _sem_outliers([p for ms, p in vs if ms >= t - DIA])
        primeira = min((ms for ms, _ in vs), default=t)
        dias = max((t - primeira) / DIA, 1 / 24)          # a coleta é recente: divide pelo período coberto
        vendas_dia = len(vs) / min(dias, 7)
        med7, med24 = _mediana(p7), _mediana(p24)
        p_ant = _sem_outliers([p for ms, p in vs if t - 7 * DIA <= ms < t - 6 * DIA])
        var7 = ((med24 / _mediana(p_ant) - 1) * 100) if med24 and p_ant else None
        ref = None
        if len(p7) >= MIN_VENDAS_REF:
            ref = min(x for x in (med7, med24) if x) if med24 and len(p24) >= 3 else med7  # o mais conservador
        v = vit.get(nome)
        anuncio = v["mn"] if v else None
        # A taxa em gema é arredondada para cima pelo jogo.
        liquido = (ref - (math.ceil(ref * TAXA) if moeda == "gems" else ref * TAXA)) if ref else None
        # Anúncio abaixo de referência ÷ 4: a mesma regra que tira vendas fora da curva. Acontece em
        # itens com dois mercados (ex.: pedras vendidas em lote a 2 gemas e avulsas a 180): comparar
        # um com o outro dá "lucro" de milhares de %. Fica de fora da revenda e dos alertas.
        anuncio_fora = bool(anuncio and ref and anuncio < ref / FATOR_OUTLIER)
        lucro = (liquido - anuncio) if (liquido is not None and anuncio and not anuncio_fora) else None
        out.append({
            "nome": nome, "moeda": moeda,
            "mediana24h": med24, "mediana7d": med7, "vendas7d": len(p7), "vendas24h": len(p24),
            "vendas_dia": round(vendas_dia, 1), "liquidez": liquidez(vendas_dia),
            "anuncio_min": anuncio, "anuncios": v["anuncios"] if v else None, "unidades_anunciadas": v["unidades"] if v else None,
            "referencia": ref, "liquido_revenda": liquido, "lucro": lucro, "anuncio_fora": anuncio_fora,
            "margem": round(lucro / anuncio * 100, 1) if lucro is not None and anuncio else None,
            # Só compara 24h com 7d quando há mais de 36h de dados (antes disso as duas janelas são quase iguais).
            "desvio": round((med24 / med7 - 1) * 100, 1)
                      if med24 and med7 and len(p24) >= 3 and t - primeira > 36 * HORA else None,
            "var7d": round(var7, 1) if var7 is not None else None,
            "snap_ms": snap,
        })
    return out


# ---------------------------------------------------------------- regras e alertas

def regras(con) -> list[dict]:
    preparar(con)
    return [dict(r) for r in con.execute("SELECT * FROM alertas_regras ORDER BY id")]


def log(con, limite=50) -> list[dict]:
    preparar(con)
    return [dict(r) for r in con.execute("SELECT * FROM alertas_log ORDER BY ms DESC LIMIT ?", (limite,))]


def _fmt(v, moeda):
    if v is None:
        return "—"
    if moeda == "coins":
        return f"{v / 1e6:.1f} mi coins".replace(".", ",") if v >= 1e6 else f"{v:,.0f} coins".replace(",", ".")
    return f"{v:,.0f} gemas".replace(",", ".") if v >= 100 else f"{v:.1f} gemas".replace(".", ",")


def _checar(regra, s) -> tuple[float, str] | None:
    """(valor que disparou, mensagem) ou None."""
    tipo, x, m = regra["tipo"], regra["valor"], s["moeda"]
    if tipo == "oportunidade":
        if s["margem"] is not None and s["margem"] >= x and s["liquidez"] != "baixa":
            sinal = "+" if s["lucro"] >= 0 else "−"
            margem = f"{abs(s['margem']):.1f}".replace(".", ",")
            return s["margem"], (f"💰 {s['nome']}: anunciado a {_fmt(s['anuncio_min'], m)}; revendendo pela referência "
                                 f"({_fmt(s['referencia'], m)}) você recebe {_fmt(s['liquido_revenda'], m)} → "
                                 f"{sinal}{_fmt(abs(s['lucro']), m)} por unidade ({sinal}{margem}%). "
                                 f"Liquidez {s['liquidez']} ({s['vendas_dia']:.0f} vendas/dia).")
    elif tipo == "abaixo":
        if s["anuncio_min"] is not None and s["anuncio_min"] <= x:
            return s["anuncio_min"], f"🔻 {s['nome']}: menor anúncio {_fmt(s['anuncio_min'], m)} (alvo ≤ {_fmt(x, m)})."
    elif tipo == "acima":
        if s["mediana24h"] is not None and s["mediana24h"] >= x:
            return s["mediana24h"], f"🔺 {s['nome']}: mediana 24h {_fmt(s['mediana24h'], m)} (alvo ≥ {_fmt(x, m)})."
    elif tipo == "variacao":
        if s["var7d"] is not None and abs(s["var7d"]) >= x:
            return abs(s["var7d"]), f"📈 {s['nome']}: {s['var7d']:+.1f}% em 7 dias (mediana 24h {_fmt(s['mediana24h'], m)})."
    return None


def avaliar(con) -> list[dict]:
    """Confere as regras ativas contra os sinais de agora. Devolve os alertas novos (já gravados no log)."""
    preparar(con)
    t = int(time.time() * 1000)
    ativas = [r for r in regras(con) if r["ativo"]]
    if not ativas:
        return []
    por_moeda = {m: calcular(con, m) for m in {r["moeda"] for r in ativas}}
    novos = []
    for r in ativas:
        for s in por_moeda[r["moeda"]]:
            if r["item"] and s["nome"] != r["item"]:
                continue
            hit = _checar(r, s)
            if not hit:
                continue
            valor, msg = hit
            ult = con.execute("SELECT valor, ms FROM alertas_log WHERE regra_id=? AND item=? AND moeda=? ORDER BY ms DESC LIMIT 1",
                              (r["id"], s["nome"], r["moeda"])).fetchone()
            if ult and t - ult["ms"] < ESPERA_REPETIR_MS:
                passo = abs(ult["valor"]) * MELHORA_PARA_REPETIR or 1e-9  # funciona com valores negativos
                melhor = valor < ult["valor"] - passo if r["tipo"] == "abaixo" else valor > ult["valor"] + passo
                if not melhor:
                    continue
            novos.append({"regra_id": r["id"], "item": s["nome"], "moeda": r["moeda"], "valor": valor, "msg": msg, "ms": t})
    return novos


def registrar(con, alerta: dict, canais: list[str]) -> None:
    con.execute("INSERT INTO alertas_log (regra_id, item, moeda, valor, msg, ms, canais) VALUES (?,?,?,?,?,?,?)",
                (alerta["regra_id"], alerta["item"], alerta["moeda"], alerta["valor"], alerta["msg"], alerta["ms"],
                 ",".join(canais)))
    con.commit()
