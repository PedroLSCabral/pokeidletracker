"""Análise de um Pokémon só, com a evolução: o Larvitar de hoje como o Tyranitar de amanhã.

A busca da loja avalia cada Pokémon como ele está. Para um Pokémon capturado (ou um anúncio que você está de
olho) a pergunta é outra: quanto ele vai valer e quanto vai caçar quando chegar à última evolução. Aqui o
volume é pequeno, então a conta pode ser mais pesada que a da busca.

O que a evolução muda e o que mantém (cliente do jogo, modal de evolução e a calculadora):
- mantém o nível, os IVs, a qualidade, a potência, o shiny, o refino e o TM; troca só as bases da espécie
  (e com elas os golpes: a última evolução ganha os golpes de assinatura de poder 600);
- precisa do nível do destino e de uma pedra do tipo da espécie (shiny usa a Shiny Stone).

A nota na evolução final é a mesma conta que o jogo faz na calculadora ("Potencial na evolução final",
`pintarPotenciais`): `notaPokemon` de `shared/nota-pokemon.mjs` com as bases do destino e a regra de que a nota
nunca cai: o maior valor entre a nota com as bases próprias e a nota de cada ancestral + 0,1 por estágio
(`GANHO_MIN_EVOLUCAO`, ancestrais de `shared/linhagem-nota.mjs`). O servidor não manda esse número pronto.

A árvore de evolução não vem toda no `creatures.json` (ele só tem `evolvesToId`/`evolveLevel`): o cliente a
monta com `shared/evolucoes-cruzadas.mjs` (elos entre gerações, cadeias truncadas, níveis corrigidos) e
`shared/evolucoes-ramificadas.mjs` (Eevee e cia.). `baixar_catalogo` (analise/caca.py) lê os dois arquivos e
grava em cada espécie do catálogo os destinos já corrigidos (`e`) e se ela tem arte jogável (`a`).

A trilha até a evolução final usa o motor de caça (`caca.Motor.xp_h`) nível a nível: em cada ponto da trilha,
os stats da forma daquele nível (as mesmas IVs/qualidade/potência com as bases dela) e a melhor hunt liberada
para o nível de treinador. O tempo sai da curva de XP do Pokémon do cliente
(`xpTotalParaNivelCliente`: ⌊50/3·(L³ − 6L² + 17L − 12)⌉), supondo que ele leva o XP inteiro de cada abate.
"""
from __future__ import annotations

import json
import math
import re

from analise import caca

# ---------------------------------------------------------------- fórmulas do jogo (shared/nota-pokemon.mjs)

STATS = ("hp", "atk", "def", "spAtk", "spDef", "speed")
EXPO_QUALIDADE = (0.95, 0.8, 0.8, 0.8, 0.8, 0.95)
BONUS_POTENCIA = (0, 0.05, 0.1, 0.25, 1)
QUALIDADE_MIN, QUALIDADE_MAX = 0.8, 1.8
IV_MIN, IV_MAX = 1, 32
MULT_SHINY, MULT_LENDARIO = 3, 4
REF_BASE = (80, 80, 80, 80, 80, 80)
GANHO_MIN_EVOLUCAO = 0.1
MERCADO_NOTA_MIN = 3.5
MERCADO_NIVEL_MIN = 50
FOLGA_NIVEL_POKEMON = 5        # o Pokémon só luta até o nível do treinador + 5
MAX_ELOS = 12
PONTOS_TRILHA = 28             # pontos da trilha nível a nível, em escala de log entre o nível de agora e o alvo
FAIXAS_NOTA = ((1, "extremamente fraco"), (2, "fraco"), (3, "mediano"), (4, "razoável"), (5, "bom"),
               (6, "forte"), (7, "poderoso"), (8, "mítico"), (9, "legendário"), (10, "divino"))


def _arred(x: float) -> int:
    """Math.round do JavaScript (meio para cima), que é o que o jogo usa."""
    return math.floor(x + 0.5)


def _r3(x: float) -> float:
    return math.floor(x * 1000 + 0.5) / 1000


def _limitar(v, lo, hi):
    return min(hi, max(lo, v))


def mult_potencia(p) -> float:
    return 1 + BONUS_POTENCIA[_limitar(int(round(p or 1)), 1, 5) - 1]


def soma_stats_nascimento(ivs, qualidade, potencia, shiny, bases, lendario=False) -> int:
    q = _limitar(float(qualidade or 1), QUALIDADE_MIN, QUALIDADE_MAX)
    mult = mult_potencia(potencia) * (MULT_SHINY if shiny else 1) * (MULT_LENDARIO if lendario else 1)
    return sum(_arred((b + 2 * iv) * q ** e * mult) for b, iv, e in zip(bases, ivs, EXPO_QUALIDADE))


def _limites_forca(bases) -> tuple[int, int]:
    lo = soma_stats_nascimento((IV_MIN,) * 6, QUALIDADE_MIN, 1, False, bases)
    hi = soma_stats_nascimento((IV_MAX,) * 6, QUALIDADE_MAX, 5, True, bases)
    return max(1, lo), max(lo + 1, hi)


_LIMITES_REF = _limites_forca(REF_BASE)


def _nota_de_forca(soma, limites) -> float:
    lo, hi = limites
    s = _limitar(soma or lo, lo, hi)
    bruta = 10 * (math.log(max(1, s)) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return _r3(_limitar(bruta, 0, 10))


def score_forca(ivs, qualidade, potencia, shiny, bases, lendario=False) -> float:
    """O score de 0 a 1 do jogo (régua comum, `limitesRef`): a soma dos stats de nascimento em log."""
    return _limitar(_nota_de_forca(soma_stats_nascimento(ivs, qualidade, potencia, shiny, bases, lendario),
                                   _LIMITES_REF) / 10, 0, 1)


def _limites_score(bases) -> tuple[float, float]:
    lo = score_forca((IV_MIN,) * 6, QUALIDADE_MIN, 1, False, bases)
    hi = score_forca((IV_MAX,) * 6, QUALIDADE_MAX, 5, True, bases)
    return lo, max(lo, hi)


def _nota_de_score(score, limites) -> float:
    lo, hi = limites
    if hi <= lo:
        return 0.0
    return _r3(10 * (_limitar(score or lo, lo, hi) - lo) / (hi - lo))


def nota_pokemon(ivs, qualidade, potencia, shiny, bases, ancestrais=()) -> float:
    """A nota (N=) de 0 a 10 dentro da espécie, com o piso dos ancestrais (a nota nunca cai ao evoluir)."""
    nota = _nota_de_score(score_forca(ivs, qualidade, potencia, shiny, bases), _limites_score(bases))
    for b, passos in ancestrais:
        anc = _nota_de_score(score_forca(ivs, qualidade, potencia, shiny, b), _limites_score(b))
        nota = max(nota, min(10.0, anc + passos * GANHO_MIN_EVOLUCAO))
    return _r3(nota)


def faixa_da_nota(n: float) -> str:
    return next((nome for teto, nome in FAIXAS_NOTA if n <= teto), "divino")


def poder(nivel, ivs, qualidade, potencia, shiny, bases, lendario=False) -> int:
    """O ⚔ do jogo: nível × 10 × score."""
    return max(1, _arred(max(1, nivel) * 10 * score_forca(ivs, qualidade, potencia, shiny, bases, lendario)))


def xp_total(nivel: float) -> float:
    """XP acumulado para chegar ao nível (xpTotalParaNivelCliente do jogo)."""
    L = nivel
    return 0.0 if L <= 1 else float(_arred(50 / 3 * (L ** 3 - 6 * L ** 2 + 17 * L - 12)))


# ---------------------------------------------------------------- a árvore (montada em baixar_catalogo)

_RE_ELO = re.compile(r"(\d+)\s*:\s*\{\s*para:\s*([\d_]+)\s*,\s*nivel:\s*([\d_]+)")
_RE_RAMO = re.compile(r"(\d+)\s*:\s*\[(.*?)\]", re.S)
_RE_DESTINO = re.compile(r"\{\s*para:\s*([\d_]+)\s*,\s*nivel:\s*([\d_]+)")
_RE_NUM = re.compile(r"(\d+)\s*:\s*([\d_]+)\s*[,}\n]")
_RE_TIPO = re.compile(r"(\d+)\s*:\s*'(\w+)'")


def _declaracoes(js: str) -> dict[str, str]:
    decl = list(caca._RE_DECLARACAO.finditer(js))
    return {d.group(1): js[d.end(): decl[i + 1].start() if i + 1 < len(decl) else len(js)] for i, d in enumerate(decl)}


def _n(s: str) -> int:
    return int(s.replace("_", ""))


def ler_tabelas(js_cruzadas: str, js_ramificadas: str, js_pedras: str = "") -> dict:
    """Lê os dois módulos de evolução do jogo (e o das pedras, se vier). Erra alto se o formato mudou."""
    c, r = _declaracoes(js_cruzadas), _declaracoes(js_ramificadas)
    elos = lambda corpo: {int(a): (_n(b), _n(n)) for a, b, n in _RE_ELO.findall(corpo)}  # noqa: E731
    t = {
        "truncadas": elos(c.get("CADEIAS_TRUNCADAS", "")),
        "entre": elos(c.get("EVOLUCOES_ENTRE_GERACOES", "")),
        "niveis": {int(a): _n(n) for a, n in _RE_NUM.findall(c.get("NIVEIS_POR_ONDE_O_ALVO_APARECE", ""))},
        "ramificadas": {int(a): [(_n(p), _n(n)) for p, n in _RE_DESTINO.findall(corpo)]
                        for a, corpo in _RE_RAMO.findall(r.get("EVOLUCOES_RAMIFICADAS", ""))},
        "pedra_forcada": {int(a): tipo for a, tipo in _RE_TIPO.findall(r.get("TIPO_DA_PEDRA_POR_ESPECIE", ""))},
        "pedras": {},
    }
    if not (t["entre"] and t["niveis"] and t["ramificadas"].get(133)):
        raise ValueError("formato dos módulos de evolução do jogo mudou")
    for tipo, nome in re.findall(r"\b([A-Z]{3,9})\s*:\s*['\"]([^'\"]+)['\"]", js_pedras or ""):
        if tipo in caca.TIPOS_ELEMENTO:
            t["pedras"].setdefault(tipo, nome)
    return t


def _ligar(especies: dict, tabela: dict) -> None:
    """aplicarElosEvolutivos: só liga quem ainda não evolui, e só para um destino que existe."""
    for pid, (para, nivel) in tabela.items():
        c = especies.get(pid)
        if c and not c.get("evolvesToId") and para in especies:
            c["evolvesToId"], c["evolveLevel"] = para, nivel


def arvore_antes_dos_golpes(especies: dict, t: dict) -> None:
    """A parte da montagem do cliente que vem antes dos golpes especiais: cadeias truncadas e o 600 → 100."""
    _ligar(especies, t["truncadas"])
    for c in especies.values():
        if c.get("evolveLevel") == 600:
            c["evolveLevel"] = 100


def arvore_depois_dos_golpes(especies: dict, t: dict, outland: set) -> None:
    """O resto, na ordem do cliente: Outland não evolui, elos entre gerações, nível padrão das ramificações
    e os níveis corrigidos."""
    for pid in outland:
        if pid in especies:
            especies[pid]["evolvesToId"] = especies[pid]["evolveLevel"] = 0
    _ligar(especies, t["entre"])
    for pid, c in especies.items():
        fam = t["ramificadas"].get(pid)
        if fam:
            padrao = next((n for p, n in fam if p == c.get("evolvesToId")), fam[0][1])
            c["evolveLevel"] = padrao
    for pid, c in especies.items():
        n = t["niveis"].get(pid)
        if n and c.get("evolvesToId"):
            c["evolveLevel"] = n


def destinos(c: dict, especies: dict, t: dict) -> list[list]:
    """destinosDeEvolucao + o tipo da pedra (tipoDaPedraDeEvolucao): [[para, nível, tipo da pedra], ...]."""
    pid, saida = int(c["pokeId"]), []
    fam = t["ramificadas"].get(pid)
    for para, nivel in (fam or []) + [(c.get("evolvesToId"), c.get("evolveLevel"))]:
        if not para or para not in especies or any(d[0] == para for d in saida):
            continue
        tipo = t["pedra_forcada"].get(pid) or (especies[para].get("type1") if fam else None) or c.get("type1")
        saida.append([int(para), int(nivel or 0), tipo])
    return saida


def tem_arte(c: dict, outland: set, especies: dict | None = None) -> bool:
    """temSpriteJogo: sem looktype não aparece; uma forma (1000-12999) precisa do looktype 60000 + id. As
    variantes Orre (13xxx) sem looktype herdam o da espécie base, como no cliente (herdarLooktypeOrre)."""
    lt, pid = c.get("looktype") or 1, int(c["pokeId"])
    if lt <= 1 and pid >= 13_000 and especies:
        lt = (especies.get(pid % 1000) or {}).get("looktype") or 1
    if lt <= 1:
        return False
    return not (pid not in outland and 1000 <= pid < 13000 and lt != 60_000 + pid)


# ---------------------------------------------------------------- a análise

class Arvore:
    """As ligações do catálogo (`e`) prontas para a análise: destinos, ancestrais e evoluções finais."""

    def __init__(self, m: caca.Motor):
        self.m = m
        self.esp = m.esp
        self.pais: dict[int, set] = {}
        for pid, e in self.esp.items():
            for para, _n, _t in e.get("e") or []:
                self.pais.setdefault(para, set()).add(pid)
        self._anc: dict = {}

    def destinos(self, pid: int, so_com_arte=False) -> list:
        return [d for d in self.esp.get(pid, {}).get("e") or []
                if d[0] in self.esp and (not so_com_arte or self.esp[d[0]].get("a", 1))]

    def ancestrais(self, pid: int) -> list[tuple]:
        """anotarLinhagemDaNota: as bases de cada ancestral e a quantos passos ele está."""
        if pid not in self._anc:
            vistos, saida, camada = {pid}, [], list(self.pais.get(pid, ()))
            for passos in range(1, MAX_ELOS + 1):
                if not camada:
                    break
                prox = []
                for a in camada:
                    if a in vistos:
                        continue
                    vistos.add(a)
                    b = self.esp.get(a, {}).get("b")
                    if b and all(x > 0 for x in b):
                        saida.append((tuple(b), passos))
                    prox += list(self.pais.get(a, ()))
                camada = prox
            self._anc[pid] = saida
        return self._anc[pid]

    def caminhos_finais(self, pid: int) -> list[list]:
        """evolucoesFinais, com o caminho até cada uma: [[(id, nível em que evolui, pedra), ...], ...]."""
        saida: dict[int, list] = {}

        def dfs(atual, caminho, vistos):
            prox = [d for d in self.destinos(atual, so_com_arte=True) if d[0] not in vistos]
            if not prox:
                if caminho:
                    saida.setdefault(atual, caminho)
                return
            for para, nivel, tipo in prox:
                dfs(para, caminho + [(para, nivel, tipo)], vistos | {para})

        dfs(pid, [], {pid})
        return list(saida.values())


def _fatores(ivs, qualidade, potencia, shiny, stats=None, bases=None, nivel=None) -> list[float]:
    """O quanto cada stat vale por ponto de (base + 2·IV) no nível 100. Com os stats reais (anúncio), sai deles
    (já com lendário e refino embutidos); sem, da fórmula do jogo (qualidade^exp × potência × shiny)."""
    q = _limitar(float(qualidade or 1), QUALIDADE_MIN, QUALIDADE_MAX)
    mult = mult_potencia(potencia) * (MULT_SHINY if shiny else 1)
    formula = [q ** e * mult for e in EXPO_QUALIDADE]
    if stats and bases and nivel:
        reais = []
        for k, b, iv, f in zip(STATS, bases, ivs, formula):
            v = stats.get(k)
            reais.append(v / ((b + 2 * iv) * nivel / 100) if v else f)
        return reais
    return formula


def _stats(bases, ivs, fatores, nivel) -> dict:
    return {k: _arred((b + 2 * iv) * nivel / 100 * f) for k, b, iv, f in zip(STATS, bases, ivs, fatores)}


def _pontos(ini: int, fim: int, fixos) -> list[int]:
    if fim <= ini:
        return sorted({ini, *fixos})
    pts = {ini, fim, *(x for x in fixos if ini <= x <= fim)}
    for i in range(1, PONTOS_TRILHA):
        pts.add(int(round(ini * (fim / ini) ** (i / PONTOS_TRILHA))))
    return sorted(pts)


def _pedra(m: caca.Motor, tipo: str | None, shiny: bool) -> str | None:
    """A pedra de evolução do tipo; Pokémon shiny usa a Shiny Stone do tipo (ex.: "Rock Shiny Stone")."""
    if not tipo:
        return None
    if shiny:
        return f"{tipo.capitalize()} Shiny Stone"
    return m.pedras.get(tipo) or f"pedra {tipo}"


def _hunt(r: dict | None) -> dict | None:
    if not r:
        return None
    return {"nome": r["hunt"], "nivel": r["nivel_hunt"], "abates_h": round(r["kph"]), "luta_s": r["luta_s"],
            "morre": r["morre"]}


def analisar(ficha: dict, nivel_treinador: int | None = None, nivel_alvo: int | None = None, comps=None,
             m: caca.Motor | None = None) -> dict:
    """A ficha de um Pokémon (`species_id`, `nivel`, `ivs`, `qualidade`, `potencia`, `shiny` e, se houver,
    `stats`, `nota`, `poder`, `refino`) → a forma de agora e cada evolução final com nota, stats, XP/h, a trilha
    nível a nível e o preço justo. `comps` é o `pokemon.Comparaveis` (sem ele, sai sem preço)."""
    m = m or caca.motor()
    arv = Arvore(m)
    sid = int(ficha["species_id"])
    esp0 = m.esp.get(sid)
    if not esp0:
        raise ValueError(f"espécie {sid} não está no catálogo do jogo")
    L0 = max(1, int(ficha["nivel"]))
    ivs = tuple(_limitar(int((ficha.get("ivs") or {}).get(k) or IV_MIN), IV_MIN, IV_MAX) for k in STATS)
    q, pot, shiny = float(ficha.get("qualidade") or 1), int(ficha.get("potencia") or 1), bool(ficha.get("shiny"))
    fat = _fatores(ivs, q, pot, shiny, ficha.get("stats"), esp0["b"], L0)
    treinador = int(nivel_treinador) if nivel_treinador else None
    avisos = []
    if ficha.get("refino"):
        avisos.append("este Pokémon tem refino: a nota projetada usa as bases sem o refino (o anúncio não diz em que stat ele está)")

    memo: dict = {}

    def xp(pid, nivel):
        k = (pid, nivel)
        if k not in memo:
            e = m.esp[pid]
            memo[k] = m.xp_h(pid, nivel, _stats(e["b"], ivs, fat, nivel), dict(zip(STATS, ivs)), e["t"], treinador)
        return memo[k]

    def preco(nome, nivel, nota):
        if comps is None:
            return None
        saida = {}
        for moeda in (("gems",) if shiny else ("gems", "coins")):
            j = comps.preco_justo(nome, shiny, moeda, nivel, nota, pot)
            if j:
                saida[moeda] = {"justo": round(j["justo"], 2), "faixa": [round(x, 2) for x in j["faixa"]],
                                "confianca": j["confianca"], "metodo": j["metodo"], "comps": j["comps"]}
        return saida or None

    def forma(pid, nivel, nota):
        e = m.esp[pid]
        r = xp(pid, nivel)
        return {"id": pid, "nome": e["n"], "tipos": e["t"], "nivel": nivel, "stats": _stats(e["b"], ivs, fat, nivel),
                "poder": poder(nivel, ivs, q, pot, shiny, e["b"]), "xp_h": round(r["xp_h"]) if r else None,
                "hunt": _hunt(r), "preco": preco(e["n"], nivel, nota)}

    nota0 = nota_pokemon(ivs, q, pot, shiny, tuple(esp0["b"]), arv.ancestrais(sid))
    if esp0.get("mega") and ficha.get("nota") is not None:
        nota0 = ficha["nota"]   # o catálogo não tem as bases próprias das megas: vale a nota do jogo
    atual = forma(sid, L0, ficha.get("nota") or nota0) | {
        "nota": nota0, "faixa": faixa_da_nota(nota0), "nota_jogo": ficha.get("nota"), "poder_jogo": ficha.get("poder")}

    finais = []
    for caminho in arv.caminhos_finais(sid):
        fid = caminho[-1][0]
        efin = m.esp[fid]
        nota = nota_pokemon(ivs, q, pot, shiny, tuple(efin["b"]), arv.ancestrais(fid))
        # Cada evolução acontece no nível dela, ou já (se o Pokémon passou desse nível).
        etapas, nivel = [], L0
        for para, nv, tipo in caminho:
            nivel = max(nivel, nv)
            etapas.append({"id": para, "nome": m.esp[para]["n"], "nivel": nivel, "nivel_jogo": nv,
                           "pedra": _pedra(m, tipo, shiny)})
        nivel_final = etapas[-1]["nivel"]
        alvo = max(nivel_final, int(nivel_alvo) if nivel_alvo else nivel_final)
        trilha, horas, sem_hunt = [], 0.0, False
        pts = _pontos(L0, alvo, [x["nivel"] for x in etapas])

        def forma_em(nv):
            f = sid
            for x in etapas:
                if x["nivel"] <= nv:
                    f = x["id"]
            return f

        for i, nv in enumerate(pts):
            f = forma_em(nv)
            r = xp(f, nv)
            if i:
                # De um ponto ao próximo vale a forma do ponto de partida (a evolução cai num ponto da trilha).
                ant = pts[i - 1]
                fa = forma_em(ant)
                ra, rb = xp(fa, ant), xp(fa, nv)
                dxp = xp_total(nv) - xp_total(ant)
                if ra and rb and ra["xp_h"] > 0 and rb["xp_h"] > 0:
                    horas += dxp * (1 / ra["xp_h"] + 1 / rb["xp_h"]) / 2
                else:
                    sem_hunt = True
            trilha.append({"nivel": nv, "id": f, "nome": m.esp[f]["n"], "xp_h": round(r["xp_h"]) if r else None,
                           "hunt": r["hunt"] if r else None, "horas": None if sem_hunt else round(horas, 2)})
        h_evol = next((p["horas"] for p in trilha if p["nivel"] == nivel_final), None)
        finais.append({
            "final": {"id": fid, "nome": efin["n"], "tipos": efin["t"]},
            "caminho": etapas, "nota": nota, "faixa": faixa_da_nota(nota),
            "mercado_ok": shiny or pot >= 5 or nota >= MERCADO_NOTA_MIN - 1e-9,
            "na_evolucao": forma(fid, nivel_final, nota),
            "no_alvo": forma(fid, alvo, nota) if alvo != nivel_final else None,
            "horas_ate_evoluir": h_evol, "horas_ate_alvo": None if sem_hunt else round(horas, 2),
            "trilha": trilha,
        })
    finais.sort(key=lambda f: -f["nota"])
    if treinador:
        teto = treinador + FOLGA_NIVEL_POKEMON
        if any(f["caminho"][-1]["nivel"] > teto for f in finais) or (nivel_alvo and int(nivel_alvo) > teto):
            avisos.append(f"o jogo só deixa o Pokémon lutar até o nível do treinador + {FOLGA_NIVEL_POKEMON} ({teto}): "
                          "a trilha supõe que o treinador sobe junto")
    return {"atual": atual, "finais": finais, "nivel_treinador": treinador, "avisos": avisos,
            "ivs": dict(zip(STATS, ivs)), "qualidade": q, "potencia": pot, "shiny": shiny,
            "ja_e_final": not finais}


# ---------------------------------------------------------------- entradas

def especies(m: caca.Motor | None = None) -> list[dict]:
    """As espécies que dá para escolher no formulário (com arte, sem mega), por nome."""
    m = m or caca.motor()
    vistos, saida = set(), []
    for pid in sorted(m.esp):
        e = m.esp[pid]
        if e.get("mega") or not e.get("a", 1) or not e.get("n") or e["n"] in vistos:
            continue
        vistos.add(e["n"])
        saida.append({"id": pid, "nome": e["n"], "evolui": bool(e.get("e"))})
    saida.sort(key=lambda x: x["nome"])
    return saida


def ficha_do_anuncio(con, anuncio_id: int) -> dict:
    r = con.execute("SELECT * FROM pk_anuncios WHERE id = ?", (anuncio_id,)).fetchone()
    if not r:
        raise ValueError("anúncio não encontrado no banco")
    js = lambda v: json.loads(v) if v else {}  # noqa: E731
    return {"species_id": r["species_id"], "nivel": r["nivel"], "ivs": js(r["ivs"]), "stats": js(r["stats"]),
            "qualidade": r["qualidade"], "potencia": r["potencia"], "shiny": bool(r["shiny"]), "nota": r["nota"],
            "poder": r["poder"], "refino": r["refino"],
            "anuncio": {"id": r["id"], "preco": r["preco"], "moeda": r["moeda"], "ativo": bool(r["ativo"])}}


def especie_por_nome(m: caca.Motor, texto: str) -> int | None:
    t = (texto or "").strip().lower()
    if t.isdigit():
        return int(t) if int(t) in m.esp else None
    achados = sorted(pid for pid, e in m.esp.items() if (e.get("n") or "").lower() == t and not e.get("mega"))
    return achados[0] if achados else None
