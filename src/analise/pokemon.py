"""Fase 4: análise do mercado de Pokémon.

  preço justo   cada Pokémon é único, então o preço vem em duas camadas:
                1) VENDAS PARECIDAS: mesma espécie, mesmo shiny, mesma moeda, mesma faixa de nível
                   e de nota. Com 5+ delas, vale a mediana (confiança alta).
                2) MODELO DE MULTIPLICADORES: preço base da espécie × multiplicador da faixa de
                   nível × da nota × da potência, aprendidos de todas as vendas (em escala log, por
                   medianas, que não se deixam levar por uma venda absurda). Serve para o que é
                   raro (nível alto, nota alta), com confiança média ou baixa.
  padrões       volume, espécies mais negociadas, quanto cada atributo multiplica o preço (relativo à
                mediana da espécie, para não confundir "P5 é caro" com "espécie cara"), horários e
                quem compra/vende em volume.
  busca         dado um orçamento, procura na loja (pk_anuncios) o Pokémon ideal segundo um objetivo.

Força para caçar: o ⚔ ("poder") do jogo NÃO mede isso bem. Ele soma os seis atributos (HP, DEF e SP.DEF
pesam tanto quanto o ataque) e passa a soma por uma escala de log (shared/nota-pokemon.mjs do jogo:
poder = nível × 10 × score, com o score em log entre o pior e o melhor nascimento). Um Pokémon com o
dobro do ATK sai com um ⚔ só ~30% maior. Na caça o que decide é o dano por golpe, que no jogo é
((2·nível/5 + 2) · poder do golpe · ATK / DEF) / 50 + 2, com ATK ou SP.ATK conforme o golpe. Por isso
a busca usa o `indice_caca` (dano de um golpe, sem o golpe e a defesa do alvo, que são iguais para
todos) para "caçar", "equilibrado" e "custo"; o ⚔ fica no objetivo "forte".
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime

from analise import caca
from coleta import importer, lojapk

DIA = 86_400_000
JANELA_COMPS_DIAS = 14
MIN_LOCAIS = 5            # vendas parecidas suficientes para usar a mediana delas direto
MIN_LOCAIS_ALTA = 8       # ...e para chamar isso de confiança alta
MIN_GRUPO = 3             # vendas da espécie (mesmo shiny e moeda) para ter um preço base
DIARIA_ANUNCIO_COINS = 100_000
FUNIL_XP = 200            # objetivo "xp": só os N melhores pelo índice de caça passam pela conta de XP/h
# Objetivo "ponte" (levar gemas de uma conta para a outra comprando e revendendo um Pokémon de piso).
# Candidatos: até FOLGA_PONTE acima do piso. O piso é a mediana dos PISO_K anúncios ativos mais baratos
# (com os filtros), e não o menor: em 11/2026 havia um anúncio isolado a 150 mil coins com o bloco do piso
# em 55-60 mi, e o menor sozinho deixava o bloco todo de fora. Anúncios abaixo do piso continuam entrando.
# 15% acima do bloco pega o piso inteiro sem chegar nos Pokémon "de verdade". Se houver poucos anúncios
# (uma espécie filtrada, shiny), o teto sobe até o MIN_PONTE-ésimo mais barato, mas nunca passa de
# TETO_PONTE × o piso.
PISO_K = 10
FOLGA_PONTE = 0.15
MIN_PONTE = 30
TETO_PONTE = 1.5

OBJETIVOS = {
    "equilibrado": "bom de caça e com preço justo (60% dano de caça, 40% desconto)",
    "xp": "mais XP por hora caçando (a melhor hunt liberada para o seu nível de treinador)",
    "caca": "melhor para caçar e upar: maior dano por golpe (nível × ATK ou SP.ATK)",
    "forte": "o maior ⚔ do jogo (a soma dos 6 atributos, a régua do ranking)",
    "barganha": "o maior desconto contra o preço justo",
    "custo": "mais dano de caça por cada gema/coin gasta",
    "nota": "a maior nota",
    "pvp": "melhor para PvP: espécie forte no meta do rank (e contra quem você perde, com nick) + poder",
    "ponte": "transferir gemas entre contas: o melhor Pokémon (para PvP) no piso de preço",
}

# Faixas usadas pelo modelo (as mesmas da aba Padrões).
FX_NIVEL = [99, 100, 200, 500, 1000, 10**9]                 # < 100 | 100 | 101-200 | 201-500 | 501-1000 | 1000+
FX_NOTA = [3.4999, 3.6999, 3.8999, 4.0999, 4.2999, 9]


def indice_caca(nivel, stats) -> tuple[float, str] | tuple[None, None]:
    """Dano de um golpe na caça, sem o que é igual para todos (poder do golpe, DEF do alvo, STAB).

    Da fórmula de dano do jogo: (2·nível/5 + 2) × ATK ou SP.ATK (o maior: o jogo usa, entre os golpes
    prontos, o que tira mais dano). Os stats do anúncio já vêm no nível dele, com IV, qualidade,
    potência e shiny. Devolve (índice, "físico"|"especial"); dividido por 100 para ficar legível.
    """
    if isinstance(stats, str):
        try:
            stats = json.loads(stats or "{}")
        except ValueError:
            stats = {}
    atk, spa = (stats or {}).get("atk") or 0, (stats or {}).get("spAtk") or 0
    if not nivel or not (atk or spa):
        return None, None
    return round((2 * nivel / 5 + 2) * max(atk, spa) / 100, 1), ("físico" if atk >= spa else "especial")


def _faixa(v, tetos):
    v = v if v is not None else tetos[1]
    return next(i for i, t in enumerate(tetos) if v <= t)


def taxa_venda(preco: float, moeda: str) -> float:
    """Comissão do jogo para vender um Pokémon (seção 13 dos Termos)."""
    if moeda == "coins":
        return preco * 0.15
    faixas = [(500, 0.13), (5000, 0.10), (float("inf"), 0.075)]
    resto, antes, taxa = preco, 0, 0.0
    for teto, pct in faixas:
        pedaco = min(resto, teto - antes)
        if pedaco <= 0:
            break
        taxa += pedaco * pct
        resto -= pedaco
        antes = teto
    return math.ceil(taxa)


def _ms(ts, ts_ms, cache={}):
    if ts_ms:
        return int(ts_ms)
    v = cache.get(ts)
    if v is None:
        v = cache[ts] = int(datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=importer.BRT).timestamp() * 1000)
    return v


# ---------------------------------------------------------------- preço justo

class Comparaveis:
    """Vendas de Pokémon dos últimos dias e o modelo de multiplicadores, por moeda."""

    def __init__(self, con, dias: int = JANELA_COMPS_DIAS):
        desde = datetime.fromtimestamp((time.time() * 1000 - dias * DIA) / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
        self.vendas: dict[str, list] = defaultdict(list)
        for r in con.execute("""SELECT base_name, shiny, currency, total, level, nota, potencia
                                FROM trades WHERE kind='pokemon' AND total > 0 AND ts >= ?""", (desde,)):
            self.vendas[r["currency"]].append((r["base_name"], int(r["shiny"] or 0), _faixa(r["level"], FX_NIVEL),
                                               _faixa(r["nota"], FX_NOTA), int(r["potencia"] or 1), r["total"]))
        self.locais: dict[tuple, list] = defaultdict(list)
        for moeda, vs in self.vendas.items():
            for esp, sh, fl, fn, pot, preco in vs:
                self.locais[(moeda, esp, sh, fl, fn)].append(preco)
        self.modelos = {m: self._ajustar(vs) for m, vs in self.vendas.items()}

    @staticmethod
    def _ajustar(vs, outliers_log: float = 1.6):
        """log(preço) = base[espécie, shiny] + nivel[faixa] + nota[faixa] + pot[P].

        Regressão com efeito fixo por espécie, resolvida por médias alternadas (backfitting). Médias
        e não medianas: com medianas, o "preço base" de uma espécie vendida quase só numa faixa de
        nível engolia o efeito do nível. Depois do primeiro ajuste, vendas muito fora do previsto
        (mais de ~5× para cima ou para baixo) saem e o ajuste é refeito."""
        def ajustar(amostra):
            base, coefs = {}, {"nivel": {}, "nota": {}, "pot": {}}
            idx = {"nivel": 2, "nota": 3, "pot": 4}
            ref = {"nivel": 1, "nota": 1, "pot": 1}       # nível 100, nota 3,5-3,7 e P1 valem 1×
            for _ in range(30):
                g = defaultdict(list)
                for v, y in amostra:
                    g[(v[0], v[1])].append(y - sum(coefs[k].get(v[i], 0.0) for k, i in idx.items()))
                base = {k: sum(x) / len(x) for k, x in g.items()}
                for k, i in idx.items():
                    res = defaultdict(list)
                    for v, y in amostra:
                        res[v[i]].append(y - base[(v[0], v[1])]
                                         - sum(coefs[o].get(v[j], 0.0) for o, j in idx.items() if o != k))
                    novos = {b: sum(r) / len(r) for b, r in res.items() if len(r) >= 5}
                    d = novos.get(ref[k], 0.0)
                    coefs[k] = {b: x - d for b, x in novos.items()}
            return base, coefs

        amostra = [(v, math.log(v[5])) for v in vs]
        base, coefs = ajustar(amostra)
        prev = lambda v: base[(v[0], v[1])] + coefs["nivel"].get(v[2], 0) + coefs["nota"].get(v[3], 0) + coefs["pot"].get(v[4], 0)  # noqa: E731
        limpa = [(v, y) for v, y in amostra if abs(y - prev(v)) <= outliers_log]
        if len(limpa) >= 0.8 * len(amostra):
            base, coefs = ajustar(limpa)
        niv, nota, pot = coefs["nivel"], coefs["nota"], coefs["pot"]
        n_grupo = Counter((v[0], v[1]) for v in vs)
        n_faixa = {"nivel": Counter(v[2] for v in vs), "nota": Counter(v[3] for v in vs), "pot": Counter(v[4] for v in vs)}
        n_esp_nivel = Counter((v[0], v[1], v[2]) for v in vs)   # a espécie já vendeu nessa faixa de nível?
        return {"base": base, "nivel": dict(niv), "nota": dict(nota), "pot": dict(pot), "n_grupo": n_grupo,
                "n_faixa": n_faixa, "n_esp_nivel": n_esp_nivel}

    def preco_justo(self, especie, shiny, moeda, nivel, nota, potencia) -> dict | None:
        sh, fl, fn, pot = int(shiny or 0), _faixa(nivel, FX_NIVEL), _faixa(nota, FX_NOTA), int(potencia or 1)
        locais = self.locais.get((moeda, especie, sh, fl, fn), [])
        mod = self.modelos.get(moeda)
        estimativa = None
        # `in base`: uma espécie cujas vendas saíram todas como fora da curva no 2º ajuste fica sem preço base.
        if mod and mod["n_grupo"].get((especie, sh), 0) >= MIN_GRUPO and (especie, sh) in mod["base"]:
            ln = mod["base"][(especie, sh)] + mod["nivel"].get(fl, 0) + mod["nota"].get(fn, 0) + mod["pot"].get(pot, 0)
            estimativa = math.exp(ln)
        if locais:  # vendas parecidas, sem as absurdas (fora de 4× a mediana delas)
            m0 = statistics.median(locais)
            locais = [p for p in locais if m0 / 4 <= p <= m0 * 4]
        if len(locais) >= MIN_LOCAIS:
            ps = sorted(locais)
            justo = statistics.median(ps)
            # P4/P5 vale mais que a mediana local (que mistura potências): aplica só o multiplicador da potência.
            if mod and pot >= 4:
                justo *= math.exp(mod["pot"].get(pot, 0))
            return {"justo": justo, "faixa": (ps[len(ps) // 4], ps[(3 * len(ps)) // 4]), "comps": len(locais),
                    "confianca": "alta" if len(locais) >= MIN_LOCAIS_ALTA else "média", "metodo": "vendas parecidas"}
        if estimativa is None:
            return None
        ng = mod["n_grupo"][(especie, sh)]
        faixas_ok = all(mod["n_faixa"][k].get(x, 0) >= 10 for k, x in (("nivel", fl), ("nota", fn), ("pot", pot)))
        # Extrapolar para uma faixa de nível que a espécie nunca vendeu não merece confiança.
        conf = "média" if ng >= 8 and faixas_ok and mod["n_esp_nivel"].get((especie, sh, fl), 0) >= 2 else "baixa"
        return {"justo": estimativa, "faixa": (estimativa * 0.6, estimativa * 1.6), "comps": len(locais) or ng,
                "confianca": conf, "metodo": "modelo"}


_modelo: tuple | None = None   # (chave, Comparaveis)


def comparaveis(con) -> Comparaveis:
    """O modelo de preço justo, refeito só quando entra venda nova no banco ou a hora vira (a janela de 14
    dias anda). Ajustar do zero leva ~3 s; sem isto, toda busca pagava esse tempo."""
    global _modelo
    chave = (con.execute("SELECT MAX(rowid) FROM trades").fetchone()[0], int(time.time() // 3600))
    if _modelo is None or _modelo[0] != chave:
        _modelo = (chave, Comparaveis(con))
    return _modelo[1]


# ---------------------------------------------------------------- busca por orçamento

def buscar(con, orcamento: float, moeda: str = "gems", objetivo: str = "equilibrado", especie: str = "",
           tipo: str = "", shiny: bool = False, potencia_min: int = 0, nivel_min: int = 0, nota_min: float = 0,
           limite: int = 60, pesos_pvp: dict[int, float] | None = None, nivel_treinador: int | None = None,
           transferir: float = 0, coins_por_gema: float | None = None) -> dict:
    lojapk.preparar(con)
    filtro = ["ativo = 1", "moeda = ?", "preco <= ?"]
    args: list = [moeda, orcamento]
    if especie:
        filtro.append("especie LIKE ?")
        args.append(f"%{especie}%")
    if tipo:
        filtro.append("tipos LIKE ?")
        args.append(f'%"{tipo.upper()}"%')
    if shiny:
        filtro.append("shiny = 1")
    if potencia_min:
        filtro.append("potencia >= ?")
        args.append(potencia_min)
    if nivel_min:
        filtro.append("nivel >= ?")
        args.append(nivel_min)
    if nota_min:
        filtro.append("nota >= ?")
        args.append(nota_min)
    ponte = None
    if objetivo == "ponte":
        # O piso vem dos anúncios com os mesmos filtros, sem o orçamento (que continua valendo como teto).
        onde = " AND ".join(f for f in filtro if f != "preco <= ?")
        sem_orc = [a for i, a in enumerate(args) if i != 1]
        precos = [r[0] for r in con.execute(f"SELECT preco FROM pk_anuncios WHERE {onde} AND preco > 0 ORDER BY preco", sem_orc)]
        if precos:
            piso = statistics.median(precos[:PISO_K])
            teto = max(piso * (1 + FOLGA_PONTE), min(precos[min(MIN_PONTE, len(precos)) - 1], piso * TETO_PONTE))
            args[1] = min(orcamento, teto)
            ponte = {"piso": piso, "teto": round(args[1], 2), "folga_pct": round(FOLGA_PONTE * 100)}
    linhas = con.execute(f"SELECT * FROM pk_anuncios WHERE {' AND '.join(filtro)}", args).fetchall()
    comps = comparaveis(con)
    res = []
    for r in linhas:
        j = comps.preco_justo(r["especie"], r["shiny"], moeda, r["nivel"], r["nota"], r["potencia"])
        preco = r["preco"] or 0
        item = {
            "id": r["id"], "species_id": r["species_id"], "especie": r["especie"], "nivel": r["nivel"], "shiny": bool(r["shiny"]), "nota": r["nota"],
            "poder": r["poder"], "iv": r["iv_total"], "ivs": json.loads(r["ivs"] or "{}"), "qualidade": r["qualidade"],
            "potencia": r["potencia"], "tipos": json.loads(r["tipos"] or "[]"), "refino": r["refino"],
            "tm": bool(r["tm_elemental"]) or bool(r["tm_aoe"]), "preco": preco, "moeda": moeda,
            "vendedor": r["vendedor"], "expira_ms": r["expira_ms"], "visto_ms": r["visto_ms"],
        }
        if j:
            liquido = j["justo"] - taxa_venda(j["justo"], moeda) - (DIARIA_ANUNCIO_COINS if moeda == "coins" else 0)
            item.update(justo=round(j["justo"], 2), faixa=j["faixa"], comps=j["comps"], confianca=j["confianca"], metodo=j["metodo"],
                        desconto=round((j["justo"] / preco - 1) * 100, 1) if preco else None,
                        revenda_liquida=liquido, lucro_revenda=liquido - preco)
        else:
            item.update(justo=None, comps=0, confianca=None, metodo=None, desconto=None, revenda_liquida=None, lucro_revenda=None)
        item["poder_por_preco"] = (r["poder"] or 0) / preco if preco else 0
        item["caca"], item["ataque"] = indice_caca(r["nivel"], r["stats"])
        item["caca_por_preco"] = (item["caca"] or 0) / preco if preco else 0
        item["_ficha"] = (r["species_id"], r["nivel"], r["stats"], r["ivs"], r["tipos"])
        res.append(item)

    # XP/h (analise/caca.py): ~5 ms por anúncio, então só para quem precisa. No objetivo "xp", o funil: os
    # FUNIL_XP melhores pelo índice de caça (quem mais bate é quem pode caçar mais alto). Nos outros, só os
    # que aparecem na lista.
    try:
        motor = caca.motor()
        aviso_xp = None
    except caca.SemDados as e:
        motor, aviso_xp = None, str(e)

    def com_xp(lista):
        for x in lista:
            r = caca.xp_do_anuncio(motor, x["id"], *x["_ficha"], nivel_treinador) if motor else None
            x["xp_h"] = round(r["xp_h"]) if r else None
            x["xp_hunt"] = r and {"nome": r["hunt"], "nivel": r["nivel_hunt"], "abates_h": round(r["kph"]),
                                  "luta_s": r["luta_s"], "morre": r["morre"]}

    # Ordenação pelo objetivo.
    def pct(chave):
        vals = sorted(x[chave] for x in res if x[chave] is not None)
        n = len(vals)
        return (lambda v: 0.5 if v is None or n < 2 else (vals.index(v) if v in vals else 0) / (n - 1))

    if objetivo == "xp":
        res.sort(key=lambda x: -(x["caca"] or 0))
        res = res[:FUNIL_XP]
        com_xp(res)
        res.sort(key=lambda x: (-(x["xp_h"] or 0), x["preco"]))
    elif objetivo == "forte":
        res.sort(key=lambda x: (-(x["poder"] or 0), x["preco"]))
    elif objetivo == "barganha":
        peso_conf = {"alta": 0, "média": 1, "baixa": 2, None: 3}
        res.sort(key=lambda x: (x["desconto"] is None, peso_conf[x["confianca"]] > 1, -(x["desconto"] or 0)))
    elif objetivo == "caca":
        res.sort(key=lambda x: (-(x["caca"] or 0), x["preco"]))
    elif objetivo == "custo":
        res.sort(key=lambda x: -x["caca_por_preco"])
    elif objetivo == "nota":
        res.sort(key=lambda x: (-(x["nota"] or 0), x["preco"]))
    elif objetivo in ("pvp", "ponte"):
        # A espécie pesa mais que o indivíduo: um P5 de uma espécie fraca no PvP perde para um P3 do meta.
        # Na ponte, o Pokémon fica na conta que mandou as gemas e vai para o PvP dela (revender um de piso
        # não sai): entre os baratos, o mais decente, com o índice de caça e o preço de desempate.
        p_poder = pct("poder")
        for x in res:
            x["nota_pvp"] = round((pesos_pvp or {}).get(x["species_id"], 0.0), 3)
            x["pontos"] = round(0.6 * x["nota_pvp"] + 0.4 * p_poder(x["poder"]), 3)
        res.sort(key=lambda x: (-x["pontos"], -(x["caca"] or 0), x["preco"]))
    else:  # equilibrado
        p_caca, p_desc = pct("caca"), pct("desconto")
        for x in res:
            # Desconto só pesa quando o preço justo é confiável; com confiança baixa ele fica neutro (0,5).
            d = p_desc(x["desconto"]) if x["confianca"] in ("alta", "média") else 0.5
            x["pontos"] = round(0.6 * p_caca(x["caca"]) + 0.4 * d, 3)
        res.sort(key=lambda x: -x["pontos"])
    total = len(linhas)
    res = res[:limite]
    if objetivo != "xp":
        com_xp(res)
    for x in res:
        x.pop("_ficha", None)
    if ponte is not None:
        ponte.update(_conta_ponte(transferir, res[0] if res else None, moeda, coins_por_gema))
    snap = con.execute("SELECT MAX(snap_ms) FROM pk_varreduras").fetchone()[0]
    return {"ponte": ponte, "total": total, "itens": res, "objetivo": objetivo, "orcamento": orcamento, "moeda": moeda,
            "nivel_treinador": nivel_treinador, "aviso_xp": aviso_xp, "funil_xp": FUNIL_XP if objetivo == "xp" else None,
            "varredura_ms": snap, "anuncios_na_loja": con.execute("SELECT COUNT(*) FROM pk_anuncios WHERE ativo=1").fetchone()[0]}


def _conta_ponte(transferir: float, primeiro: dict | None, moeda: str, coins_por_gema: float | None) -> dict:
    """A conta da transferência: a conta que recebe anuncia o Pokémon em gemas por `transferir` e a outra
    compra. Recebe o preço menos a comissão progressiva; o custo é a comissão + o Pokémon (o 1º da lista,
    convertido pelo câmbio se em coins) + a diária de anúncio. Em gemas; sem câmbio, a parte em coins
    fica de fora do total e vai à parte."""
    if not transferir or transferir <= 0:
        return {"transferir": None}
    comissao = taxa_venda(transferir, "gems")
    out = {"transferir": transferir, "comissao": comissao, "recebe": transferir - comissao,
           "coins_por_gema": coins_por_gema, "diaria_coins": DIARIA_ANUNCIO_COINS}
    if not primeiro:
        return out
    preco = primeiro["preco"]
    em_coins = DIARIA_ANUNCIO_COINS + (preco if moeda == "coins" else 0)
    em_gemas = comissao + (preco if moeda == "gems" else 0)
    if coins_por_gema:
        out.update(pokemon_gemas=round(preco / coins_por_gema if moeda == "coins" else preco, 1),
                   diaria_gemas=round(DIARIA_ANUNCIO_COINS / coins_por_gema, 1),
                   custo_total_gemas=round(em_gemas + em_coins / coins_por_gema, 1), custo_coins_sem_cambio=None)
    else:
        out.update(pokemon_gemas=preco if moeda == "gems" else None, diaria_gemas=None,
                   custo_total_gemas=em_gemas, custo_coins_sem_cambio=em_coins)
    out["custo_pct"] = round(out["custo_total_gemas"] / transferir * 100, 1)
    return out


# ---------------------------------------------------------------- padrões

FAIXAS = {
    "potencia": [(1, 1, "P1"), (2, 2, "P2"), (3, 3, "P3"), (4, 4, "P4"), (5, 5, "P5")],
    "iv": [(0, 79, "< 80"), (80, 109, "80–109"), (110, 139, "110–139"), (140, 169, "140–169"), (170, 192, "170+")],
    "nota": [(0, 3.4999, "< 3,5"), (3.5, 3.6999, "3,5–3,7"), (3.7, 3.8999, "3,7–3,9"), (3.9, 4.0999, "3,9–4,1"),
             (4.1, 4.2999, "4,1–4,3"), (4.3, 9, "4,3+")],
    "qualidade": [(0, 0.9999, "< 1,0"), (1.0, 1.1999, "1,0–1,2"), (1.2, 1.3999, "1,2–1,4"), (1.4, 1.5999, "1,4–1,6"),
                  (1.6, 9, "1,6+")],
    "nivel": [(0, 99, "< 100"), (100, 100, "100"), (101, 200, "101–200"), (201, 500, "201–500"),
              (501, 1000, "501–1.000"), (1001, 10**9, "1.000+")],
}
COLUNA = {"potencia": "potencia", "iv": "iv_total", "nota": "nota", "qualidade": "qualidade", "nivel": "level"}


def padroes(con, moeda: str = "gems", dias: int = 7) -> dict:
    lojapk.preparar(con)
    t = int(time.time() * 1000)
    desde = datetime.fromtimestamp((t - dias * DIA) / 1000, importer.BRT).strftime("%Y-%m-%d %H:%M")
    todas = con.execute("SELECT * FROM trades WHERE kind='pokemon' AND ts >= ?", (desde,)).fetchall()
    vendas = [r for r in todas if r["currency"] == moeda]
    primeira = min((_ms(r["ts"], r["ts_ms"]) for r in todas), default=t)
    dias_cobertos = max((t - primeira) / DIA, 1 / 24)

    # Mediana por grupo (espécie, shiny) para os multiplicadores relativos.
    grupo = defaultdict(list)
    for r in vendas:
        grupo[(r["base_name"], int(r["shiny"] or 0))].append(r["total"])
    med_grupo = {k: statistics.median(v) for k, v in grupo.items() if len(v) >= 5}
    rel = [(r, r["total"] / med_grupo[(r["base_name"], int(r["shiny"] or 0))])
           for r in vendas if (r["base_name"], int(r["shiny"] or 0)) in med_grupo]

    premios = {}
    for dim, faixas in FAIXAS.items():
        col = COLUNA[dim]
        linhas = []
        for lo, hi, rot in faixas:
            rs = [x for r, x in rel if r[col] is not None and lo <= r[col] <= hi]
            linhas.append({"faixa": rot, "vendas": len(rs), "mult": round(statistics.median(rs), 2) if len(rs) >= 3 else None})
        premios[dim] = linhas
    # Nível, nota e potência: o efeito ISOLADO de cada um, do modelo de preço (os outros atributos
    # ficam iguais). A comparação simples acima mistura efeitos (nota alta costuma vir com nível alto).
    mod = Comparaveis(con, max(dias, JANELA_COMPS_DIAS)).modelos.get(moeda)
    if mod:
        rotulos = {"nivel": [f[2] for f in FAIXAS["nivel"]], "nota": [f[2] for f in FAIXAS["nota"]],
                   "potencia": [f[2] for f in FAIXAS["potencia"]]}
        for dim, chave, desloc in (("nivel", "nivel", 0), ("nota", "nota", 0), ("potencia", "pot", 1)):
            n = mod["n_faixa"]["pot" if dim == "potencia" else dim]
            premios[dim] = [{"faixa": rot, "vendas": n.get(i + desloc, 0),
                             "mult": round(math.exp(mod[chave][i + desloc]), 2) if (i + desloc) in mod[chave] else None}
                            for i, rot in enumerate(rotulos[dim])]
    # Shiny: mediana do shiny dividida pela do comum da mesma espécie.
    razoes = [statistics.median(grupo[(e, 1)]) / statistics.median(grupo[(e, 0)])
              for (e, s) in grupo if s == 1 and grupo.get((e, 0)) and len(grupo[(e, 0)]) >= 3]
    premios["shiny"] = [{"faixa": "shiny vs comum (mesma espécie)", "vendas": len(razoes),
                         "mult": round(statistics.median(razoes), 2) if razoes else None}]

    # Espécies mais negociadas + oferta na loja.
    loja = defaultdict(list)
    for r in con.execute("SELECT especie, preco FROM pk_anuncios WHERE ativo=1 AND moeda=?", (moeda,)):
        loja[r["especie"]].append(r["preco"])
    por_esp = defaultdict(list)
    for r in vendas:
        por_esp[r["base_name"]].append(r["total"])
    especies = []
    for e, ps in sorted(por_esp.items(), key=lambda kv: -len(kv[1]))[:30]:
        ps_ord = sorted(ps)
        vend_dia = len(ps) / min(dias_cobertos, dias)
        especies.append({
            "especie": e, "vendas": len(ps), "vendas_dia": round(vend_dia, 1), "mediana": statistics.median(ps),
            "p25": ps_ord[len(ps) // 4], "p75": ps_ord[(3 * len(ps)) // 4], "min": ps_ord[0],
            "anuncios": len(loja.get(e, [])), "menor_anuncio": min(loja[e]) if loja.get(e) else None,
            "dias_estoque": round(len(loja.get(e, [])) / vend_dia, 1) if vend_dia else None,
        })

    horas = Counter(datetime.fromtimestamp(_ms(r["ts"], r["ts_ms"]) / 1000, importer.BRT).hour for r in vendas)

    def top(campo):
        c = defaultdict(list)
        for r in vendas:
            if r[campo]:
                c[r[campo]].append(r["total"])
        return [{"nome": n, "qtd": len(v), "mediana": statistics.median(v), "total": sum(v)}
                for n, v in sorted(c.items(), key=lambda kv: -len(kv[1]))[:10]]

    snap = con.execute("SELECT MAX(snap_ms) FROM pk_varreduras").fetchone()[0]
    sumidos = con.execute("SELECT COUNT(*) FROM pk_anuncios WHERE ativo=0 AND sumiu_ms >= ?", (t - DIA,)).fetchone()[0]
    return {
        "moeda": moeda, "dias": dias, "dias_cobertos": round(dias_cobertos, 2),
        "resumo": {
            "vendas": len(vendas), "vendas_outra_moeda": len(todas) - len(vendas),
            "volume": sum(r["total"] for r in vendas), "mediana": statistics.median([r["total"] for r in vendas]) if vendas else None,
            "especies": len(por_esp), "shiny_pct": round(100 * sum(1 for r in vendas if r["shiny"]) / len(vendas), 1) if vendas else None,
            "anuncios_loja": sum(len(v) for v in loja.values()), "especies_loja": len(loja),
            "varredura_ms": snap, "sumiram_24h": sumidos,
        },
        "premios": premios, "especies": especies,
        "horas": [{"hora": h, "vendas": horas.get(h, 0)} for h in range(24)],
        "compradores": top("buyer"), "vendedores": top("seller"),
        "taxa_exemplos": [{"preco": p, "taxa": taxa_venda(p, moeda)} for p in ((100, 500, 1000, 5000, 20000) if moeda == "gems"
                                                                             else (10**6, 10**7, 10**8, 10**9))],
    }
