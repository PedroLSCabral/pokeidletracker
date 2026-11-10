"""Vender o que dropou: em qual moeda, por quanto e quando.

Para um item (e uma quantidade), olha as duas moedas e responde:
  - qual moeda rende mais, com preferência pelas gemas (são as que viram dinheiro);
  - três preços de anúncio: rápido (fica em 1º da fila), normal e paciente, já com a taxa;
  - se é hora de vender: pico (vender agora), queda passageira (esperar), queda constante
    (vender logo), alta constante (pode segurar, mas com prazo) ou estável (tanto faz).

A tendência é a reta de Theil-Sen sobre as medianas por hora: robusta a vendas fora da curva.
A oscilação normal (sigma) vem dos resíduos dessa reta. Com poucos dias de coleta, tudo isso
sai com "confiança baixa", e a média de 7 dias calculada pelo próprio jogo ajuda a enxergar
além do que o robô já coletou.
"""
from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from datetime import datetime

import importer
from sinais import _ms, _sem_outliers

TAXA = 0.15
USD_POR_GEMA = 0.009
HORA = 3600_000
DIA = 24 * HORA
JANELA_DIAS = 14              # quanto histórico entra na tendência
MIN_HORAS_TENDENCIA = 24      # menos que isso de dados: sem tendência
MIN_PONTOS_TENDENCIA = 12     # horas com venda
PICO_SIGMAS = 1.0             # o preço recente a 1 sigma da reta já é pico ou queda
TENDENCIA_MIN_DIA = 1.0       # %/dia: abaixo disso a tendência é "estável", mesmo se significativa
PREFERENCIA_GEMAS = 0.05      # coins só ganha se render 5% a mais que gemas, já contando a troca
SEGURAR_MAX_DIAS = 3          # horizonte do "pode segurar": tendência curta vira rápido
SEMANA_ESTAVEL_DIA = 0.5      # %/dia: a média de 7 dias do jogo andando menos que isso = semana estável


# ---------------------------------------------------------------- utilidades

def _mediana(v):
    return statistics.median(v) if v else None


def _pct(v_ordenado, p):
    if not v_ordenado:
        return None
    k = (len(v_ordenado) - 1) * p
    i = int(k)
    j = min(i + 1, len(v_ordenado) - 1)
    return v_ordenado[i] + (v_ordenado[j] - v_ordenado[i]) * (k - i)


def _n(v: float, casas: int = 1, sinal: bool = False) -> str:
    """Número com vírgula decimal, como no resto do painel."""
    return f"{v:{'+' if sinal else ''}.{casas}f}".replace(".", ",")


def liquido(preco: float, moeda: str) -> float:
    """O que o vendedor recebe. Em gemas o jogo arredonda a taxa para cima."""
    if moeda == "gems":
        return preco - math.ceil(preco * TAXA)
    return math.floor(preco * (1 - TAXA))


def _arredondar(preco: float, moeda: str) -> int:
    """Gemas inteiras; coins com 3 algarismos significativos (750.000.000, 4.120.000…)."""
    if moeda == "gems":
        return max(1, int(round(preco)))
    if preco < 1000:
        return max(1, int(round(preco)))
    passo = 10 ** (int(math.log10(preco)) - 2)
    return int(round(preco / passo) * passo)


def _passo(preco: float, moeda: str) -> int:
    """Quanto abaixo do menor anúncio para ficar em 1º da fila."""
    if moeda == "gems" or preco < 1000:
        return 1
    return 10 ** (int(math.log10(preco)) - 2)


def _theil_sen(xs, ys):
    """Inclinação e intercepto robustos: medianas das inclinações entre todos os pares."""
    inc = [(ys[j] - ys[i]) / (xs[j] - xs[i])
           for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i]]
    if not inc:
        return None, None
    b = statistics.median(inc)
    a = statistics.median([y - b * x for x, y in zip(xs, ys)])
    return b, a


# ---------------------------------------------------------------- leitura

def _vendas(con, nome: str, moeda: str, desde_ms: int) -> list[tuple[int, float, int]]:
    desde = datetime.fromtimestamp(desde_ms / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
    v = [(_ms(r["ts"], r["ts_ms"]), r["unit_price"], r["qty"]) for r in con.execute(
        "SELECT ts, ts_ms, unit_price, qty FROM trades WHERE kind='item' AND currency=? AND base_name=? AND ts>=?",
        (moeda, nome, desde))]
    bons = set(_sem_outliers([p for _, p, _ in v]))
    return sorted(x for x in v if x[1] in bons)


def _vitrine(con, nome: str, t: int) -> dict:
    row = con.execute("SELECT id FROM itens WHERE nome = ?", (nome,)).fetchone()
    if not row:
        return {}
    snaps = con.execute("SELECT * FROM vitrine WHERE item_id = ? AND snap_ms >= ? ORDER BY snap_ms",
                        (row[0], t - 7 * DIA)).fetchall()
    if not snaps:
        return {}
    ult = snaps[-1]
    out = {"anuncios": ult["anuncios"], "unidades": ult["unidades"], "snap_ms": ult["snap_ms"]}
    for m, col in (("gems", "gems"), ("coins", "coins")):
        out[m] = {"min": ult[f"min_{col}"], "media7": ult[f"media7_{col}"],
                  "serie_media7": [(s["snap_ms"], s[f"media7_{col}"]) for s in snaps if s[f"media7_{col}"]]}
    return out


def cambio(con, t: int | None = None) -> dict:
    """Quantos coins vale 1 gema no mercado: a razão das medianas dos itens vendidos nas duas
    moedas nas últimas 48 h, pesada pelo volume (mediana ponderada)."""
    t = t or int(time.time() * 1000)
    desde = datetime.fromtimestamp((t - 2 * DIA) / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
    precos = defaultdict(lambda: {"gems": [], "coins": []})
    for r in con.execute("SELECT base_name, currency, unit_price FROM trades WHERE kind='item' AND ts >= ?", (desde,)):
        precos[r["base_name"]][r["currency"]].append(r["unit_price"])
    pares = []
    for nome, p in precos.items():
        g, c = _sem_outliers(p["gems"]), _sem_outliers(p["coins"])
        if len(g) >= 5 and len(c) >= 5:
            pares.append((statistics.median(c) / statistics.median(g), min(len(g), len(c)), nome))
    if not pares:
        return {"coins_por_gema": None, "itens": 0, "base": []}
    pares.sort()
    meio, acum = sum(w for _, w, _ in pares) / 2, 0
    for razao, w, _ in pares:
        acum += w
        if acum >= meio:
            break
    base = [n for _, _, n in sorted(pares, key=lambda x: -x[1])[:5]]
    return {"coins_por_gema": razao, "itens": len(pares), "base": base}


# ---------------------------------------------------------------- análise de uma moeda

def tendencia(vendas, t: int) -> dict | None:
    """Reta de Theil-Sen no log das medianas por hora. None se ainda não há dados para isso."""
    por_hora = defaultdict(list)
    for ms, p, _ in vendas:
        por_hora[ms // HORA].append(p)
    if len(por_hora) < MIN_PONTOS_TENDENCIA:
        return None
    hs = sorted(por_hora)
    span_h = hs[-1] - hs[0]
    if span_h < MIN_HORAS_TENDENCIA:
        return None
    xs = [(h * HORA + HORA / 2 - t) / DIA for h in hs]           # dias até agora (negativos)
    ys = [math.log(statistics.median(por_hora[h])) for h in hs]
    b, a = _theil_sen(xs, ys)
    if b is None:
        return None
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    mr = statistics.median(res)
    sigma = max(1.4826 * statistics.median([abs(r - mr) for r in res]), 0.01)
    span_d = span_h / 24
    erro_b = sigma * math.sqrt(12 / len(xs)) / span_d              # erro da inclinação (x uniforme)
    pct_dia = (math.exp(b) - 1) * 100
    return {"pct_dia": round(pct_dia, 2), "nivel": math.exp(a), "sigma_pct": round((math.exp(sigma) - 1) * 100, 1),
            "sigma_log": sigma, "dias": round(span_d, 1), "horas_com_venda": len(xs),
            "significativa": abs(b) > 2 * erro_b and abs(pct_dia) >= TENDENCIA_MIN_DIA}


def _tendencia_jogo(serie_media7, t: int) -> float | None:
    """%/dia da média de 7 dias do jogo. Ela é uma média móvel: sobe quando o preço de hoje
    está acima do de 7 dias atrás, então enxerga uma semana mesmo com pouca coleta."""
    pts = [(ms, v) for ms, v in serie_media7 if v and v > 0]
    if len(pts) < 8 or pts[-1][0] - pts[0][0] < 12 * HORA:
        return None
    b, _ = _theil_sen([(ms - t) / DIA for ms, _ in pts], [math.log(v) for _, v in pts])
    return None if b is None else round((math.exp(b) - 1) * 100, 2)


def inicio_coleta(con) -> int | None:
    """Quando o banco começou a ter vendas de itens: a base para "vendas por dia" de itens raros."""
    r = con.execute("SELECT MIN(ts) FROM trades WHERE kind='item'").fetchone()[0]
    return _ms(r, None) if r else None


def analisar_moeda(con, nome: str, moeda: str, qtd: int, t: int, vit: dict, inicio: int | None) -> dict:
    vendas = _vendas(con, nome, moeda, t - JANELA_DIAS * DIA)
    v_moeda = vit.get(moeda) or {}
    anuncio_min, media7_jogo = v_moeda.get("min"), v_moeda.get("media7")
    if not vendas and not anuncio_min and not media7_jogo:
        return {"moeda": moeda, "tem_mercado": False}

    v48 = sorted(p for ms, p, _ in vendas if ms >= t - 2 * DIA)
    v24 = [p for ms, p, _ in vendas if ms >= t - DIA]
    v12 = [p for ms, p, _ in vendas if ms >= t - 12 * HORA]
    v7 = [(ms, q) for ms, _, q in vendas if ms >= t - 7 * DIA]
    # Ritmo pelo tempo de coleta (não pela primeira venda do item, que num item raro seria ontem).
    dias_cob = max(min(7.0, (t - (inicio or t - DIA)) / DIA), 1 / 24)
    vendas_dia = len(v7) / dias_cob
    un_dia = sum(q for _, q in v7) / dias_cob
    fino = len(v48) < 5            # mercado fino nesta moeda: as vendas não bastam para dar preço

    tend = tendencia(vendas, t)
    recentes = [p for ms, p, _ in vendas if ms >= t - 3 * HORA]
    if len(recentes) < 3:
        recentes = [p for _, p, _ in vendas[-5:]]
    recente = _mediana(recentes)
    med24 = _mediana(v24) if len(v24) >= 3 else None
    if not fino:
        normal = _mediana(v12) if len(v12) >= 5 else (med24 or _mediana(v48))
    else:
        normal = media7_jogo or _mediana([p for _, p, _ in vendas[-10:]]) or anuncio_min

    desvio = None   # quantos sigmas o preço recente está da reta
    if tend and recente:
        desvio = round((math.log(recente) - math.log(tend["nivel"])) / tend["sigma_log"], 2)

    # ------------------------------------------------ preços de anúncio
    p10, p25, p50, p75 = (_pct(v48, q) for q in (0.10, 0.25, 0.50, 0.75)) if not fino else (None,) * 4
    if anuncio_min:
        rapido = anuncio_min - _passo(anuncio_min, moeda)     # 1 abaixo do menor anúncio: 1º da fila
        if p10:
            rapido = max(rapido, p10)                         # mas sem entregar abaixo de quase todas as vendas
    else:
        rapido = p25 or normal
    normal = normal or rapido
    anuncio_baixo = False
    if rapido and normal and (rapido < normal * 0.5 or liquido(rapido, moeda) <= 0):
        # Menor anúncio muito abaixo do preço de referência, num mercado que quase não negocia:
        # ficar em 1º da fila seria dar o item. Sem preço "rápido" nesse caso.
        rapido, anuncio_baixo = None, True
    normal = max(normal, rapido or 0)
    precos = {"rapido": rapido, "normal": normal, "paciente": max(p75 or 0, normal * 1.05)}
    opcoes = {}
    for k, p in precos.items():
        if not p:
            continue
        p = _arredondar(p, moeda)
        un = liquido(p, moeda)
        frac = sum(1 for x in v48 if x >= p) / len(v48) if not fino else None
        opcoes[k] = {"preco": p, "liquido_un": un, "liquido_total": un * qtd,
                     "usd_total": round(un * qtd * USD_POR_GEMA, 2) if moeda == "gems" else None,
                     "vendas_acima": round(frac * 100) if frac is not None else None}
    if "rapido" in opcoes and un_dia > 0:
        opcoes["rapido"]["espera_min"] = round(qtd / un_dia * 24 * 60)

    return {
        "moeda": moeda, "tem_mercado": True, "fino": fino, "anuncio_muito_baixo": anuncio_baixo,
        "vendas_14d": len(vendas), "vendas_24h": len(v24), "vendas_dia": round(vendas_dia, 1), "unidades_dia": round(un_dia, 1),
        "mediana24h": med24, "recente": recente, "normal": normal, "desvio_sigmas": desvio,
        "faixa48h": {"p10": p10, "p25": p25, "p50": p50, "p75": p75, "n": len(v48)},
        "anuncio_min": anuncio_min, "media7_jogo": media7_jogo,
        "vs_media7_jogo": round((recente / media7_jogo - 1) * 100, 1) if recente and media7_jogo else None,
        "tendencia": tend, "tendencia_jogo_pct_dia": _tendencia_jogo(v_moeda.get("serie_media7", []), t),
        "opcoes": opcoes,
        "primeira_venda": vendas[0][0] if vendas else None,
    }


# ---------------------------------------------------------------- decisões

def _quando(a: dict) -> dict:
    """Vender agora, esperar ou segurar, a partir da análise de uma moeda."""
    tend, z, tj = a.get("tendencia"), a.get("desvio_sigmas"), a.get("tendencia_jogo_pct_dia")
    linha_j = f"A média de 7 dias do jogo anda {_n(tj, 1, True)}% por dia." if tj is not None else None
    if not tend:
        motivos = ["Ainda faltam vendas para ver a tendência: precisa de 1 dia de dados, com venda em 12 horas diferentes."]
        return {"acao": "sem_dados", "titulo": "Sem dados para escolher o momento",
                "motivos": motivos + ([linha_j] if linha_j else [])}

    pd_, sig, sg = tend["pct_dia"], tend["significativa"], tend["sigma_pct"]
    sobe, desce = sig and pd_ > 0, sig and pd_ < 0
    dias_txt = _n(tend["dias"], 1)
    motivos = [f"Tendência de {dias_txt} dias: {_n(pd_, 1, True)}% por dia." if sig
               else f"Sem tendência clara em {dias_txt} dias ({_n(pd_, 1, True)}% por dia, dentro da oscilação).",
               f"Oscilação normal: ±{_n(sg, 0)}% em torno da tendência."] + ([linha_j] if linha_j else [])

    if z is not None and z >= PICO_SIGMAS:
        return {"acao": "agora", "titulo": "Vender agora: o preço está num pico",
                "motivos": [f"As vendas das últimas horas estão {_n(z, 1)}× a oscilação normal acima da tendência.",
                            "Picos assim costumam voltar ao normal."] + motivos}
    semana_sobe = tj is not None and tj > SEMANA_ESTAVEL_DIA
    semana_cai = tj is not None and tj < -SEMANA_ESTAVEL_DIA
    if desce and not semana_sobe:
        return {"acao": "agora", "titulo": "Vender logo: a queda é constante",
                "motivos": ["O preço cai de forma contínua, não é um tombo passageiro. Esperar tende a render menos."]
                + motivos}
    if desce:
        extra = (["E as vendas das últimas horas ainda estão abaixo dessa reta."]
                 if z is not None and z <= -PICO_SIGMAS else [])
        return {"acao": "misto", "titulo": "Sinais mistos: venda pelo preço normal, sem baixar",
                "motivos": ["Os últimos dias caem, mas a média de 7 dias do jogo sobe: pode ser só uma correção "
                            "depois de uma semana de alta."] + extra
                + ["Sem pressa de vender barato. Também não dá para contar com a volta da alta."] + motivos}
    if sobe and semana_cai:
        return {"acao": "misto", "titulo": "Sinais mistos: venda pelo preço normal",
                "motivos": ["Os últimos dias sobem, mas a média de 7 dias do jogo cai: a alta pode ser só um repique."]
                + motivos}
    if z is not None and z <= -PICO_SIGMAS:
        return {"acao": "esperar", "titulo": "Esperar: a queda parece passageira",
                "motivos": [f"As vendas das últimas horas estão {_n(abs(z), 1)}× a oscilação normal abaixo da "
                            "tendência, e a tendência não está caindo.",
                            "Anuncie pelo preço normal, sem acompanhar a queda, e deixe o comprador chegar."] + motivos,
                "alvo": a["normal"]}
    if sobe:
        alvo = a["normal"] * (1 + pd_ / 100) ** SEGURAR_MAX_DIAS
        ganho = (alvo / a["normal"] - 1) * 100
        compensa = ganho > sg
        return {"acao": "segurar" if compensa else "tanto_faz",
                "titulo": "Pode segurar alguns dias" if compensa else "Subindo devagar: tanto faz o momento",
                "motivos": [f"Em {SEGURAR_MAX_DIAS} dias, a tendência levaria o preço a ~{_n(ganho, 0)}% acima de hoje."
                            + ("" if compensa else " É menos que a oscilação normal, então a espera não compensa."),
                            "Não segure para sempre: tendência de poucos dias vira rápido. Uma saída é anunciar "
                            "pelo preço paciente e deixar a alta chegar até você."] + motivos,
                "alvo": alvo if compensa else None}
    return {"acao": "tanto_faz", "titulo": "Preço estável: venda quando quiser",
            "motivos": ["Nem pico nem queda: o preço está dentro da oscilação normal."] + motivos}


def _confianca(a: dict, t: int) -> str:
    if not a.get("primeira_venda"):
        return "baixa"
    dias = (t - a["primeira_venda"]) / DIA
    if dias < 3 or a["vendas_14d"] < 20:
        return "baixa"
    return "média" if dias < 7 else "alta"


def _melhor_hora(con, nome: str, moeda: str, t: int) -> dict | None:
    """Faixa de 3 horas com mais unidades compradas (horário de Brasília). Só com 3+ dias de dados."""
    vendas = _vendas(con, nome, moeda, t - JANELA_DIAS * DIA)
    if not vendas or t - vendas[0][0] < 3 * DIA:
        return None
    por_h = [0] * 24
    for ms, _, q in vendas:
        por_h[datetime.fromtimestamp(ms / 1000, importer.BRT).hour] += q
    total = sum(por_h) or 1
    ini = max(range(24), key=lambda h: por_h[h] + por_h[(h + 1) % 24] + por_h[(h + 2) % 24])
    parte = (por_h[ini] + por_h[(ini + 1) % 24] + por_h[(ini + 2) % 24]) / total
    return {"inicio": ini, "fim": (ini + 3) % 24, "parte": round(parte * 100)}


def _montagem(con, nome: str, gems: dict, montagens: dict, raridades: list, t: int) -> dict | None:
    """Para fragmentos: juntar 10 e montar rende mais que vender os 10?"""
    m = next(((frag, suf) for frag, suf in montagens.values() if frag == nome), None)
    if not m or not gems.get("tem_mercado") or "normal" not in gems["opcoes"]:
        return None
    _, sufixo = m
    ev, ev_comum, falta = 0.0, 0.0, []
    for pt, en, chance in raridades:
        alvo = f"{en} {sufixo}"
        vs = [p for ms, p, _ in _vendas(con, alvo, "gems", t - 7 * DIA)]
        preco = _mediana(vs) if len(vs) >= 3 else None
        if preco is None:
            v = _vitrine(con, alvo, t).get("gems") or {}
            preco = v.get("media7") or v.get("min")
        if preco is None:
            falta.append(pt)
            continue
        ev += chance * liquido(preco, "gems")
        if pt not in ("Mítica", "Lendária"):
            ev_comum += chance * liquido(preco, "gems")
    dez = 10 * gems["opcoes"]["normal"]["liquido_un"]
    return {"sufixo": sufixo, "ev_liquido": round(ev), "dez_fragmentos": dez,
            "vantagem": round((ev / dez - 1) * 100, 1) if dez else None,
            "vantagem_sem_raras": round((ev_comum / dez - 1) * 100, 1) if dez else None, "sem_preco": falta}


def analisar(con, nome: str, qtd: int = 1, montagens: dict | None = None, raridades: list | None = None) -> dict:
    t = int(time.time() * 1000)
    qtd = max(1, int(qtd))
    vit = _vitrine(con, nome, t)
    inicio = inicio_coleta(con)
    gems = analisar_moeda(con, nome, "gems", qtd, t, vit, inicio)
    coins = analisar_moeda(con, nome, "coins", qtd, t, vit, inicio)
    cb = cambio(con, t)

    # ------------------------------------------------ em qual moeda
    escolha = {"moeda": "gems", "motivo": "", "coins_em_gemas": None, "vantagem_coins": None}
    eq = None
    g_ok = gems.get("tem_mercado") and "normal" in gems.get("opcoes", {})
    c_ok = coins.get("tem_mercado") and "normal" in coins.get("opcoes", {})
    if c_ok and cb["coins_por_gema"]:
        # Para virar gema, o coin ainda precisa de outra venda (comprar algo em coins e vender em gemas): mais 15%.
        eq = coins["opcoes"]["normal"]["liquido_un"] / cb["coins_por_gema"] * (1 - TAXA)
        escolha["coins_em_gemas"] = round(eq, 2)
        if g_ok and gems["opcoes"]["normal"]["liquido_un"] > 0:
            escolha["vantagem_coins"] = round((eq / gems["opcoes"]["normal"]["liquido_un"] - 1) * 100, 1)
    if g_ok and c_ok and gems["fino"] and not coins["fino"]:
        escolha.update(moeda="coins", motivo=(
            f"Em gemas este item quase não vende ({gems['vendas_14d']} venda(s) em {JANELA_DIAS} dias), e em coins "
            "sai rápido. Se preferir arriscar em gemas, anuncie pelo preço normal e espere: pode levar dias."))
    elif g_ok and c_ok and escolha["vantagem_coins"] is not None:
        v = escolha["vantagem_coins"]
        if v > PREFERENCIA_GEMAS * 100 and coins.get("vendas_dia", 0) >= 1:
            escolha.update(moeda="coins", motivo=f"Em coins rende {_n(v, 0)}% a mais, mesmo depois de trocar os coins por gemas.")
        elif v > 0:
            escolha["motivo"] = (f"Em coins renderia só {_n(v, 0)}% a mais depois da troca. É menos que os "
                                 f"{_n(PREFERENCIA_GEMAS * 100, 0)}% que compensam sair das gemas.")
        else:
            vezes = gems["opcoes"]["normal"]["liquido_un"] / max(eq, 1e-9)
            if vezes >= 20:
                escolha["motivo"] = "Em coins este item vale quase nada perto do preço em gemas."
            else:
                quanto = f"{_n(vezes, 0)} vezes mais" if vezes >= 3 else f"{_n((vezes - 1) * 100, 0)}% a mais"
                escolha["motivo"] = f"Em gemas rende {quanto} do que em coins, já contando a troca."
    elif g_ok:
        escolha["motivo"] = "Sem dados de coins suficientes para comparar." if not c_ok else "Sem câmbio coins/gemas para comparar."
    elif c_ok:
        escolha.update(moeda="coins", motivo="Este item quase não é vendido em gemas.")
    else:
        escolha.update(moeda=None, motivo="Sem vendas nem anúncios deste item para analisar.")
    for a in (gems, coins):
        if a.get("tem_mercado"):
            a["quando"] = _quando(a)
            a["confianca"] = _confianca(a, t)
            a["melhor_hora"] = _melhor_hora(con, nome, a["moeda"], t)

    # Dias de estoque: unidades anunciadas ÷ unidades vendidas por dia (nas duas moedas).
    un_dia = (gems.get("unidades_dia") or 0) + (coins.get("unidades_dia") or 0)
    estoque_dias = round(vit["unidades"] / un_dia, 1) if vit.get("unidades") and un_dia > 0 else None
    return {"nome": nome, "qtd": qtd, "agora": t, "escolha": escolha, "cambio": cb,
            "gems": gems, "coins": coins, "taxa": TAXA, "usd_por_gema": USD_POR_GEMA,
            "montagem": _montagem(con, nome, gems, montagens or {}, raridades or [], t),
            "estoque_unidades": vit.get("unidades"), "anuncios": vit.get("anuncios"), "estoque_dias": estoque_dias}
