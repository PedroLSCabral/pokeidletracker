"""Precificar um Pokémon: por quanto vender agora e se vale evoluir (e subir de nível) antes de vender.

Junta o que o projeto já sabe fazer:
  - o preço justo (`pokemon.Comparaveis`: vendas parecidas ou o modelo de multiplicadores);
  - a concorrência da loja (`pk_anuncios` ativos): um anúncio parecido mais barato puxa o preço rápido para
    baixo, e um anúncio MELHOR (nível, nota e potência pelo menos iguais) mais barato é teto para qualquer preço,
    porque o comprador levaria aquele;
  - a comissão progressiva do jogo (`pokemon.taxa_venda`) e a diária do anúncio (`DIARIA_ANUNCIO_COINS`);
  - a moeda, como no botão vender dos itens (`venda.cambio`, `PREFERENCIA_GEMAS`): shiny só vai em gemas;
  - a simulação até a evolução final (`evolucao.analisar`) e o motor de caça, para o tempo.

Os três preços, no espírito do botão vender dos itens (`venda.analisar_moeda`):
  - rápido: 1 passo abaixo do anúncio parecido mais barato (o 1º da fila), sem passar do preço justo e sem
    descer do piso (o p10 das vendas parecidas, ou 60% do justo pelo modelo);
  - normal: o preço justo;
  - paciente: o p75 das vendas parecidas (no mínimo o justo + 15%).
  Os três respeitam o teto dos anúncios melhores e mais baratos.

Vale a pena evoluir/subir? O preço de mercado de um Pokémon anda em degraus (o modelo separa o nível nas faixas
<100, 100, 101-200, 201-500, 501-1000 e 1000+; e a nota sobe na evolução). Em cada ponto da trilha (os mesmos
pontos da análise de evolução, mais a entrada de cada faixa de nível), o ganho é o valor líquido em gemas
naquele ponto − o valor líquido de vender agora − as pedras de evolução. O melhor ponto é o de mais gemas por
hora investida (o tempo é caçando sem parar, do nível de agora até lá). Se você diz quanto vale a sua hora
(`valor_hora`, em gemas), o melhor ponto passa a ser o de maior lucro depois de descontar esse custo. Depois
do melhor ponto, cada hora a mais rende menos gemas que a média até ali: é onde parar e vender.
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime

from analise import evolucao, pokemon, venda
from analise.sinais import _sem_outliers
from coleta import importer

FOLGA_RAPIDO = 1.0          # o rápido nunca passa do justo
PISO_MODELO = 0.6           # sem vendas parecidas, o rápido não desce de 60% do justo (a faixa do modelo)
PACIENTE_MIN = 1.15         # o paciente fica pelo menos 15% acima do justo
FOLGA_NOTA = 0.05           # um anúncio "melhor" pode ter até 0,05 de nota a menos (arredondamento do jogo)
NIVEL_MAX_SEM_TREINADOR = 1001
# A entrada de cada faixa de nível do modelo de preço (FX_NIVEL: <100 | 100 | 101-200 | 201-500 | 501-1000 | 1000+).
ENTRADAS_FAIXA = tuple(t + 1 for t in pokemon.FX_NIVEL[:-1])


def pode_vender(nivel, nota, shiny, potencia) -> bool:
    """Regra do mercado do jogo: nível ≥ 50 e nota ≥ 3,5 (shiny e P5 passam livres da nota)."""
    if (nivel or 0) < evolucao.MERCADO_NIVEL_MIN:
        return False
    return bool(shiny) or int(potencia or 1) >= 5 or (nota or 0) >= evolucao.MERCADO_NOTA_MIN - 1e-9


def _diaria_gemas(cb: float | None) -> float:
    return pokemon.DIARIA_ANUNCIO_COINS / cb if cb else 0.0


def liquido(preco: float, moeda: str) -> float:
    """O que chega na conta: o preço − a comissão progressiva do jogo para Pokémon."""
    return preco - pokemon.taxa_venda(preco, moeda)


def em_gemas(valor: float, moeda: str, cb: float | None) -> float | None:
    """Coins viram gemas pelo câmbio, descontando os 15% da troca (como no botão vender dos itens)."""
    if moeda == "gems":
        return valor
    return valor / cb * (1 - venda.TAXA) if cb else None


# ---------------------------------------------------------------- valor rápido (para a trilha)

def valor_justo_gemas(comps, cb, nome, shiny, nivel, nota, potencia) -> dict | None:
    """O valor líquido em gemas de vender pelo preço justo, na moeda que rende mais. None se não vende."""
    if not pode_vender(nivel, nota, shiny, potencia):
        return None
    melhor = None
    for moeda in (("gems",) if shiny else ("gems", "coins")):
        j = comps.preco_justo(nome, shiny, moeda, nivel, nota, potencia)
        if not j:
            continue
        g = em_gemas(liquido(j["justo"], moeda), moeda, cb)
        if g is None:
            continue
        g -= _diaria_gemas(cb)
        if moeda == "coins" and melhor and g < melhor["gemas"] * (1 + venda.PREFERENCIA_GEMAS):
            continue
        melhor = {"gemas": g, "moeda": moeda, "justo": j["justo"], "confianca": j["confianca"], "metodo": j["metodo"]}
    return melhor


# ---------------------------------------------------------------- preços de venda de agora

def _pct(v, p):
    return venda._pct(sorted(v), p) if v else None


def _anuncios(con, nome, shiny, moeda) -> list:
    return con.execute("""SELECT id, nivel, nota, potencia, preco FROM pk_anuncios
                          WHERE ativo = 1 AND especie = ? AND shiny = ? AND moeda = ? AND preco > 0
                          ORDER BY preco""", (nome, int(bool(shiny)), moeda)).fetchall()


def precos_moeda(con, comps, cb, nome, shiny, nivel, nota, potencia, moeda, ignorar_anuncio=None) -> dict | None:
    """Rápido, normal e paciente numa moeda, com o líquido de cada um. None se não há preço justo."""
    j = comps.preco_justo(nome, shiny, moeda, nivel, nota, potencia)
    if not j:
        return None
    justo = j["justo"]
    sh, fl, fn = int(bool(shiny)), pokemon._faixa(nivel, pokemon.FX_NIVEL), pokemon._faixa(nota, pokemon.FX_NOTA)
    locais = comps.locais.get((moeda, nome, sh, fl, fn), [])
    if locais:
        m0 = statistics.median(locais)
        locais = [p for p in locais if m0 / 4 <= p <= m0 * 4]
    parecidos, melhores = [], []
    for a in _anuncios(con, nome, shiny, moeda):
        if a["id"] == ignorar_anuncio:
            continue
        if (pokemon._faixa(a["nivel"], pokemon.FX_NIVEL), pokemon._faixa(a["nota"], pokemon.FX_NOTA)) == (fl, fn):
            parecidos.append(a)
        if a["nivel"] >= nivel and (a["nota"] or 0) >= (nota or 0) - FOLGA_NOTA and (a["potencia"] or 1) >= potencia:
            melhores.append(a)
    passo = lambda p: venda._passo(p, moeda)  # noqa: E731
    teto = melhores[0]["preco"] - passo(melhores[0]["preco"]) if melhores else None
    if len(locais) >= pokemon.MIN_LOCAIS:
        piso, alto = _pct(locais, 0.10), max(_pct(locais, 0.75), justo * PACIENTE_MIN)
    else:
        piso, alto = justo * PISO_MODELO, justo * PACIENTE_MIN
    if parecidos:
        rapido = min(justo * FOLGA_RAPIDO, parecidos[0]["preco"] - passo(parecidos[0]["preco"]))
    else:
        rapido = _pct(locais, 0.25) if len(locais) >= pokemon.MIN_LOCAIS else justo * 0.85
    concorrencia_baixa = rapido < piso
    rapido = max(rapido, piso)
    normal, paciente = justo, alto
    if teto is not None:
        rapido, normal, paciente = min(rapido, teto), min(normal, teto), min(paciente, teto)
    normal = max(normal, rapido)
    paciente = max(paciente, normal)
    vendas_dia = len(locais) / pokemon.JANELA_COMPS_DIAS
    opcoes = {}
    for k, p in (("rapido", rapido), ("normal", normal), ("paciente", paciente)):
        p = venda._arredondar(p, moeda)
        liq = liquido(p, moeda)
        opcoes[k] = {"preco": p, "taxa": pokemon.taxa_venda(p, moeda), "liquido": liq,
                     "liquido_gemas": None if em_gemas(liq, moeda, cb) is None
                     else round(em_gemas(liq, moeda, cb) - _diaria_gemas(cb), 1),
                     "vendas_acima": round(100 * sum(1 for x in locais if x >= p) / len(locais)) if locais else None}
    return {
        "moeda": moeda, "justo": round(justo, 2), "faixa": [round(x, 2) for x in j["faixa"]],
        "confianca": j["confianca"], "metodo": j["metodo"], "comps": j["comps"],
        "vendas_parecidas_14d": len(locais), "vendas_dia": round(vendas_dia, 2),
        "anuncios_parecidos": len(parecidos), "menor_parecido": parecidos[0]["preco"] if parecidos else None,
        "anuncios_melhores": len(melhores), "menor_melhor": melhores[0]["preco"] if melhores else None,
        "teto_melhor": teto is not None and teto < justo, "concorrencia_abaixo_do_piso": concorrencia_baixa,
        "opcoes": opcoes,
    }


def precos_agora(con, comps, cb, nome, shiny, nivel, nota, potencia, ignorar_anuncio=None) -> dict:
    """As duas moedas (shiny só gemas) e a escolha, como no botão vender dos itens."""
    if not pode_vender(nivel, nota, shiny, potencia):
        motivo = (f"nível abaixo de {evolucao.MERCADO_NIVEL_MIN}" if (nivel or 0) < evolucao.MERCADO_NIVEL_MIN
                  else f"nota abaixo de {str(evolucao.MERCADO_NOTA_MIN).replace('.', ',')}")
        return {"pode_vender": False, "motivo": f"ainda não vai ao mercado ({motivo})", "moedas": {}, "moeda": None}
    moedas = {}
    for moeda in (("gems",) if shiny else ("gems", "coins")):
        p = precos_moeda(con, comps, cb, nome, shiny, nivel, nota, potencia, moeda, ignorar_anuncio)
        if p:
            moedas[moeda] = p
    g = (moedas.get("gems") or {}).get("opcoes", {}).get("normal", {}).get("liquido_gemas")
    c = (moedas.get("coins") or {}).get("opcoes", {}).get("normal", {}).get("liquido_gemas")
    escolha, motivo = None, ""
    if g is not None and c is not None:
        v = (c / g - 1) * 100 if g > 0 else None
        if v is not None and v > venda.PREFERENCIA_GEMAS * 100:
            escolha, motivo = "coins", f"Em coins rende {venda._n(v, 0)}% a mais, já contando a troca dos coins por gemas."
        else:
            escolha = "gems"
            motivo = ("Em gemas rende mais." if v is None or v <= 0 else
                      f"Em coins renderia só {venda._n(v, 0)}% a mais depois da troca: não compensa sair das gemas.")
    elif "gems" in moedas:
        escolha = "gems"
        motivo = "Shiny só se anuncia em gemas." if shiny else ("Sem vendas em coins para comparar." if "coins" not in moedas
                                                               else "Sem câmbio coins/gemas para comparar.")
    elif "coins" in moedas:
        escolha, motivo = "coins", "Sem vendas parecidas em gemas: só dá para estimar em coins."
    return {"pode_vender": bool(moedas), "motivo": motivo if moedas else "sem vendas da espécie para estimar o preço",
            "moedas": moedas, "moeda": escolha}


# ---------------------------------------------------------------- pedras

def preco_item_gemas(con, nome: str, cb: float | None, t: int | None = None) -> dict | None:
    """Quanto custa uma pedra, em gemas: o caminho mais barato entre comprar em gemas e comprar em coins (pelo
    câmbio). Em cada moeda, a mediana das vendas de 7 dias sem as fora da curva; sem vendas, a média de 7 dias
    do jogo ou o menor anúncio. Em 11/2026 as pedras giravam ~20 mil vendas por semana em coins (~100 mil coins
    cada, quase nada em gemas pelo câmbio), e em gemas umas dezenas, de 2 a 200 gemas: o mais barato é o coins."""
    t = t or int(time.time() * 1000)
    desde = datetime.fromtimestamp((t - 7 * venda.DIA) / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
    rotas = []
    for moeda in ("gems", "coins"):
        ps = _sem_outliers([r[0] for r in con.execute(
            "SELECT unit_price FROM trades WHERE kind='item' AND base_name = ? AND currency = ? AND ts >= ?",
            (nome, moeda, desde))])
        if len(ps) >= 3:
            v, fonte = statistics.median(ps), f"mediana de {len(ps)} vendas em 7 dias"
        else:
            vit = venda._vitrine(con, nome, t).get(moeda) or {}
            v, fonte = vit.get("media7") or vit.get("min"), "vitrine do jogo"
        # Comprar em coins custa gemas pelo câmbio mais os 15% da troca (o inverso de `em_gemas`).
        g = (v if moeda == "gems" else v / cb / (1 - venda.TAXA) if cb else None) if v else None
        if g is not None:
            rotas.append({"gemas": round(g, 3), "moeda": moeda, "preco": v, "fonte": fonte})
    return min(rotas, key=lambda x: x["gemas"], default=None)


# ---------------------------------------------------------------- vale a pena evoluir / subir?

def _avaliar_trilha(trilha, forma_id, nome, nota, base, custo, ficha, comps, cb, valor_hora) -> dict:
    """Em cada ponto da trilha já na forma `forma_id`, o ganho em gemas e as gemas por hora."""
    pontos = []
    for p in trilha:
        if p["id"] != forma_id or p["horas"] is None:
            continue
        v = valor_justo_gemas(comps, cb, nome, ficha["shiny"], p["nivel"], nota, ficha["potencia"])
        ganho = None if v is None else v["gemas"] - base - custo
        h = p["horas"]
        pontos.append({"nivel": p["nivel"], "horas": h, "xp_h": p["xp_h"],
                       "valor": None if v is None else round(v["gemas"], 1),
                       "moeda": v and v["moeda"], "confianca": v and v["confianca"],
                       "ganho": None if ganho is None else round(ganho, 1),
                       "gemas_h": None if ganho is None or h <= 0 else round(ganho / h, 2),
                       "lucro_tempo": None if ganho is None or valor_hora is None else round(ganho - valor_hora * h, 1)})
    validos = [x for x in pontos if x["ganho"] is not None]
    if valor_hora is not None:
        melhor = max(validos, key=lambda x: (x["lucro_tempo"], -x["nivel"]), default=None)
        vale = bool(melhor and melhor["lucro_tempo"] > 0)
    else:
        com_tempo = [x for x in validos if x["gemas_h"] is not None and x["ganho"] > 0]
        melhor = max(com_tempo, key=lambda x: (x["gemas_h"], -x["nivel"]), default=None)
        if melhor is None:   # sem tempo (o Pokémon já está no ponto): vale se ganha alguma coisa
            melhor = max((x for x in validos if x["ganho"] > 0), key=lambda x: x["ganho"], default=None)
        vale = melhor is not None
    for x in pontos:
        x["melhor"] = melhor is not None and x is melhor
    primeiro = next((x for x in validos if x["ganho"] > 0), None)
    return {"pontos": pontos, "melhor": melhor, "vale": vale, "primeiro_lucro": primeiro and primeiro["nivel"],
            "sem_preco": not validos}


def precificar(con, comps, r: dict, ficha: dict, valor_hora: float | None = None) -> dict:
    """`r` é o `evolucao.analisar` (com a trilha esticada) e `ficha`, a do Pokémon. Devolve os preços de agora e,
    para cada evolução final (ou para subir de nível, se já é a última forma), se vale e até que nível."""
    cb = venda.cambio(con)["coins_por_gema"]
    a = r["atual"]
    nota_agora = r.get("nota_atual_mercado") or a["nota"]
    an = ficha.get("anuncio") or {}
    agora = precos_agora(con, comps, cb, a["nome"], r["shiny"], a["nivel"], nota_agora, r["potencia"], an.get("id"))
    base_v = valor_justo_gemas(comps, cb, a["nome"], r["shiny"], a["nivel"], nota_agora, r["potencia"])
    base = base_v["gemas"] if base_v else 0.0
    f_dados = {"shiny": r["shiny"], "potencia": r["potencia"]}
    pedras_cache: dict = {}
    saida_finais, avisos = [], []
    for f in r["finais"]:
        custo, pedras, falta = 0.0, [], []
        for etapa in f["caminho"]:
            nome_p = etapa.get("pedra")
            if not nome_p:
                continue
            if nome_p not in pedras_cache:
                pedras_cache[nome_p] = preco_item_gemas(con, nome_p, cb)
            pr = pedras_cache[nome_p]
            pedras.append({"nome": nome_p, "gemas": pr and pr["gemas"], "moeda": pr and pr["moeda"],
                           "preco": pr and pr["preco"], "fonte": pr and pr["fonte"]})
            if pr:
                custo += pr["gemas"]
            else:
                falta.append(nome_p)
        av = _avaliar_trilha(f["trilha"], f["final"]["id"], f["final"]["nome"], f["nota"], base, custo, f_dados,
                             comps, cb, valor_hora)
        nivel_final = f["caminho"][-1]["nivel"]
        na_evol = precos_agora(con, comps, cb, f["final"]["nome"], r["shiny"], nivel_final, f["nota"], r["potencia"])
        melhor_precos = None
        if av["melhor"] and av["melhor"]["nivel"] != nivel_final:
            melhor_precos = precos_agora(con, comps, cb, f["final"]["nome"], r["shiny"], av["melhor"]["nivel"],
                                         f["nota"], r["potencia"])
        saida_finais.append({"final": f["final"], "nota": f["nota"], "custo_pedras": round(custo, 1),
                             "pedras": pedras, "pedras_sem_preco": falta, "na_evolucao": na_evol,
                             "no_melhor": melhor_precos, **av})
    subir = None
    if r.get("subir"):
        subir = _avaliar_trilha(r["subir"], a["id"], a["nome"], nota_agora, base, 0.0, f_dados, comps, cb, valor_hora)
        if subir["melhor"] and subir["melhor"]["nivel"] != a["nivel"]:
            subir["no_melhor"] = precos_agora(con, comps, cb, a["nome"], r["shiny"], subir["melhor"]["nivel"],
                                              nota_agora, r["potencia"])
    if not cb:
        avisos.append("sem câmbio coins/gemas: os valores em coins não entram na comparação")
    return {"agora": agora, "valor_agora": round(base, 1), "valor_agora_moeda": base_v and base_v["moeda"],
            "coins_por_gema": cb, "valor_hora": valor_hora, "finais": saida_finais, "subir": subir,
            "diaria_coins": pokemon.DIARIA_ANUNCIO_COINS, "avisos": avisos}


def horizonte(nivel_treinador: int | None) -> int:
    """Até que nível procurar: o teto do jogo (treinador + 5) ou, sem treinador, a entrada da última faixa."""
    if nivel_treinador:
        return int(nivel_treinador) + evolucao.FOLGA_NIVEL_POKEMON
    return NIVEL_MAX_SEM_TREINADOR
