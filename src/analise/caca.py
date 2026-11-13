"""XP por hora de caça de um Pokémon, rápido o bastante para ordenar a loja.

Uma calculadora da comunidade simula a caça golpe a golpe, nível a nível, nas 1.043 hunts: segundos por
Pokémon. A busca precisa de centenas em cerca de um segundo, então aqui a conta tem três atalhos (~5 ms
por Pokémon, e a mesma hunt e o mesmo número que a busca completa em 300 casos de teste):

1. **Só o nível de agora.** Na busca a pergunta é "quanto XP/h ele faz hoje", não a trilha até um nível.
2. **Estimativa antes de simular** (`_estimar`). Para cada hunt liberada, uma conta de 1º grau pela média
   de longo prazo: cada golpe sai uma vez por recarga (que corre também na caminhada entre abates) e a
   Investida a cada 2 s de luta. As hunts são vistas da mais alta para a mais baixa, e a busca para quando
   nem o teto de uma hunt (3600 ÷ tempo do mapa × XP do abate) alcança as melhores estimativas.
3. **Mini-luta só nas 8 melhores estimativas** (`_hunt`): 16 rolagens de HP do selvagem; a cada intervalo,
   o golpe pronto de maior dano, senão a Investida; os trechos só de Investida são saltados de uma vez.

As regras vêm dos módulos públicos do jogo (`shared/*.mjs`, ver docs/ARQUITETURA.md, seção 14.1):
- dano = ((2·nível/5 + 2) · poder · ATK/DEF) / 50 + 2, × STAB 1,5 × efetividade × 0,925 (rolagem média);
  na caça a efetividade é ampliada (`ampliacaoHunt`, 1,5): 2× vira 2,5× e 0,5× vira 0,33×;
- os golpes: os do catálogo, trocados pelos das planilhas de balanceamento (`golpes-planilhas.mjs`), mais
  os de assinatura (poder 600, recarga 60 s) que o jogo dá às últimas evoluções; megas com o golpe de mega;
- selvagem: stats = (base + 2·IV) · nível/100, IV médio 16; HP de combate = máx(24, HP·12) × 5;
  dano dele × 1,8; um golpe a cada 1,4 s;
- XP do abate = ⌊0,6·n²⌋ + 8 até o nível 150; acima, 13.500 · (n/150)^1,25;
- Investida: poder 30, físico, recarga 2 s; intervalo entre golpes 0,9 s; os dois −10 ms por IV de SPD;
  a recarga dos golpes cai até 7% com o SPD-base e o IV de SPD;
- com poção automática só morre quem leva, de um golpe, mais que o HP inteiro.

Ficam de fora AoE, TM, bike, casa, bônus de XP, dia sazonal e o tempo de cada mapa (usa a mediana). Contra a
calculadora, na mesma hunt, o XP/h fica entre −15% e +17%. Os dados: o catálogo de espécies e golpes sai
dos arquivos públicos do jogo (`baixar_catalogo`, 1 vez por dia, pelo robô); as hunts e as constantes saem
do `welcome` que o robô já recebe ao entrar (`guardar_welcome`).
"""
from __future__ import annotations

import heapq
import json
import math
import os
import re
import time
import urllib.request

import caminhos

URL_ASSETS = "https://pokeidle.io/assets/"
CATALOGOS = ("creatures.json", "creatures-novos.json", "creatures-outland-novos.json", "creatures-formas.json")
OVERRIDES = "creatures-audit-overrides.json"
SPRITES_LAB = "creatures-sprites-lab.json"   # correções de looktype (decidem se a espécie tem arte jogável)
URL_SHARED = "https://pokeidle.io/shared/"
MODULOS_EVOLUCAO = ("evolucoes-cruzadas.mjs", "evolucoes-ramificadas.mjs", "pedras-evolucao.mjs")
URL_PLANILHAS = "https://pokeidle.io/shared/golpes-planilhas.mjs"   # os golpes das planilhas de balanceamento
USER_AGENT = "Mozilla/5.0 (PokeIdle Tracker)"

# Regras de combate (Pokepédia e módulos shared/ do jogo).
RAND_MEDIO = 0.925
STAB = 1.5
GAP_S = 0.9
GAP_SELVAGEM_S = 1.4
INVESTIDA_PODER = 30
INVESTIDA_CD_S = 2.0
PISO_CD_S = 0.4
S_POR_IV_SPD = 0.010
PODER_MINIMO = 15
HP_COMBATE_MULT, HP_COMBATE_MIN = 12, 24
IV_SELVAGEM = 16
IVS_HP_AMOSTRA = tuple(range(1, 33, 2))
# Ritmo: tempo por abate de quem mata de um golpe (mediana dos mapas no simulador do jogo 1.409) e o
# quanto a luta encurta a caminhada até o próximo bando (telemetria publicada pela calculadora).
S_POR_ABATE_MAPA = 3.41
CAMINHADA_DO_MAPA, CAMINHADA_PISO_S, CAMINHADA_TAU_S = 0.83, 1.41, 2.8
MORTE_S = 3 + 20.6 * 0.51           # volta ao jogo + corrida de volta
# "Não mata" para a conta. Precisa ser folgado: abaixo do nível 150 o XP do abate cresce com o quadrado do
# nível do selvagem, e um Pokémon fraco faz mais XP/h numa hunt alta de luta longa (30 s por abate) do que
# numa baixa de um golpe só.
MAX_GOLPES_POR_ABATE = 400
MAX_LUTA_S = 300                    # o mesmo limite, pela conta fechada (antes de simular)
CANDIDATAS = 8                      # hunts que passam da estimativa para a mini-luta
EF_MAXIMA = 5.5                     # 4× (dupla vantagem) ampliado pela caça: 1 + 3 × 1,5
PADRAO_CONSTS = {"ampliacaoHunt": 1.5, "multHpSelvagem": 5, "multDanoSelvagem": 1.8}
DIAGONAL = {"FIRE": 0.5, "WATER": 0.5, "ELECTRIC": 0.5, "GRASS": 0.5, "ICE": 0.5, "POISON": 0.5,
            "PSYCHIC": 0.5, "DARK": 0.5, "STEEL": 0.5, "GHOST": 2, "DRAGON": 2}


def xp_do_nivel(n: float) -> float:
    return (6 * n * n) // 10 + 8 if n <= 150 else round(13_500 * (n / 150) ** 1.25)


def tempo_morto(s_mapa: float, luta: float) -> float:
    """Tempo entre abates com `luta` segundos de luta: o bando anda até o herói enquanto ele luta."""
    encurta = max(0.0, CAMINHADA_DO_MAPA * s_mapa - CAMINHADA_PISO_S)
    return s_mapa - encurta * (1 - math.exp(-luta / CAMINHADA_TAU_S))


# ---------------------------------------------------------------- dados do jogo

def guardar_welcome(msg: dict) -> dict:
    """Tira do `welcome` só o que a caça usa (hunts, constantes, tabela de tipos) e grava em data/jogo/.

    Não guarda o estado da conta. Grava também um esqueleto (só chaves, tipos e tamanhos) para conferir
    o formato quando o jogo mudar. Devolve um resumo para o log.
    """
    hunts, consts, tipos = None, {}, None

    def andar(o, prof=0):
        nonlocal hunts, tipos
        if prof > 8:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("ampliacaoHunt", "multHpSelvagem", "multDanoSelvagem") and isinstance(v, (int, float)):
                    consts[k] = v
                elif k == "tabelaTipos" and isinstance(v, dict) and tipos is None:
                    tipos = v
                elif k == "shinyStone" and isinstance(v, dict) and isinstance(v.get("custo"), (int, float)):
                    consts["shinyStoneCusto"] = v["custo"]   # fragmentos por Shiny Stone (analise/precificar.py)
                elif isinstance(v, list) and len(v) > 50 and all(isinstance(x, dict) and "slug" in x for x in v[:20]):
                    if hunts is None or len(v) > len(hunts):
                        hunts = v
                else:
                    andar(v, prof + 1)
        elif isinstance(o, list):
            for x in o[:3]:
                andar(x, prof + 1)

    andar(msg)
    caminhos.JOGO.mkdir(parents=True, exist_ok=True)
    resumo = {"hunts": len(hunts or []), "consts": consts, "tabelaTipos": bool(tipos)}
    if hunts:
        dados = {"salvo_ms": int(time.time() * 1000), "hunts": hunts, "consts": consts, "tabelaTipos": tipos}
        _gravar_json(caminhos.WELCOME_JOGO, dados)
    _gravar_json(caminhos.JOGO / "welcome-esqueleto.json", _esqueleto(msg))
    return resumo


def _esqueleto(o, prof=0):
    if prof > 6:
        return "…"
    if isinstance(o, dict):
        return {k: _esqueleto(v, prof + 1) for k, v in list(o.items())[:80]}
    if isinstance(o, list):
        return [f"lista[{len(o)}]", _esqueleto(o[0], prof + 1)] if o else "lista[0]"
    return type(o).__name__


def _gravar_json(caminho, dados) -> None:
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, caminho)


def _baixar(nome: str):
    req = urllib.request.Request(URL_ASSETS + nome, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _baixar_texto(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


TIPOS_ELEMENTO = ("NORMAL", "FIRE", "WATER", "GRASS", "ELECTRIC", "ICE", "FIGHTING", "POISON", "GROUND", "FLYING",
                  "PSYCHIC", "BUG", "ROCK", "GHOST", "DRAGON", "DARK", "STEEL", "FAIRY")
GOLPE_600_CD_MS = 60_000
GOLPE_MEGA_CD_MS = 30_000
FANTASMA_OUTLAND = range(10_000, 10_501)   # espelhos fantasmas da Outland: não ganham golpe especial


def injetar_golpes_600(c: dict) -> None:
    """Os golpes de assinatura (poder 600) que o cliente do jogo injeta (shared/golpes-especiais.mjs).

    Toda última evolução (menos mega e espelho fantasma) leva um golpe de 600 de cada tipo seu; quem tem
    um tipo só leva dois do mesmo tipo. A categoria é o lado de ataque mais forte da espécie e a recarga é
    de 60 s. Os nomes não importam para a conta, só poder, tipo, categoria e recarga.
    """
    for a in c.get("attacks") or []:
        if (a.get("power") or 0) >= 600:
            a["cooldownMs"] = GOLPE_600_CD_MS
    if c.get("evolvesToId") or int(c["pokeId"]) in FANTASMA_OUTLAND or c.get("megaDeDex") is not None or c.get("golpesFechados"):
        return
    golpes = [a for a in c.get("attacks") or [] if a.get("type") in TIPOS_ELEMENTO and (a.get("power") or 0) > 10]
    cat = "PHYSICAL" if (c.get("baseAtk") or 0) >= (c.get("baseSpAtk") or 0) else "SPECIAL"
    for a in golpes:
        if (a.get("power") or 0) >= 600 and not a.get("categoriaFixa"):
            a["category"] = cat
    tipos = list(dict.fromkeys(t for t in (c.get("type1"), c.get("type2")) if t in TIPOS_ELEMENTO))
    for t in tipos:
        if not any((a.get("power") or 0) >= 600 and a.get("type") == t for a in golpes):
            golpes.append({"power": 600, "type": t, "category": cat, "cooldownMs": GOLPE_600_CD_MS, "learnLevel": 1})
    de600 = [a for a in golpes if (a.get("power") or 0) >= 600]
    if len(de600) == 1:
        golpes.append({**de600[0], "category": cat, "learnLevel": 1})
    c["attacks"] = golpes


def cooldown_do_poder(poder: float) -> int:
    """A curva de recarga do jogo (shared/cooldown-golpes.mjs): 10 s no poder 15, 30 s no 100, 60 s no 600."""
    p = poder if poder > PODER_MINIMO else PODER_MINIMO
    seg = 10 + (p - PODER_MINIMO) * 20 / 85 if p <= 100 else 30 + (p - 100) * 30 / 500
    return round(seg * 10) * 100


_RE_DECLARACAO = re.compile(r"^(?:export )?const (\w+) = ", re.M)
_RE_ESPECIE = re.compile(r"^\s*(\d+):\s*\[(.*?)^\s*\],", re.M | re.S)
_RE_GOLPE = re.compile(r"\[\s*(['\"])(.*?)\1\s*,\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*(\d+)\s*(?:,\s*(\w+)\s*)?\]")


def ler_planilhas(js: str) -> tuple[list[dict], set, dict]:
    """Lê shared/golpes-planilhas.mjs: (tabelas na ordem em que o jogo aplica, ids das tabelas "fechadas",
    golpes das megas por pokeId da mega). Cada golpe: {power, type, category, cooldownMs, learnLevel...}."""
    tabelas = {}
    # Um pedaço por declaração (de um `const X = ` até o próximo): uma tabela vazia `{};` não engole a seguinte.
    decl = list(_RE_DECLARACAO.finditer(js))
    for i, d in enumerate(decl):
        nome = d.group(1)
        if not nome.startswith("GOLPES_"):
            continue
        corpo = js[d.end(): decl[i + 1].start() if i + 1 < len(decl) else len(js)]
        t = {}
        for pid, linhas in _RE_ESPECIE.findall(corpo):
            golpes = []
            for _q, _nome, tipo, cat, poder, marca in _RE_GOLPE.findall(linhas):
                poder = int(poder)
                g = {"power": poder, "type": tipo, "category": cat, "learnLevel": 1,
                     "cooldownMs": GOLPE_MEGA_CD_MS if marca == "MEGA" else cooldown_do_poder(poder)}
                if poder >= 600 or marca == "MEGA":
                    g["categoriaFixa"] = True
                golpes.append(g)
            if golpes:
                t[int(pid)] = golpes
        tabelas[nome] = t

    def nomes(trecho_re):
        m = re.search(trecho_re, js, re.S | re.M)
        return re.findall(r"GOLPES_\w+", m.group(1)) if m else []

    ordem = [tabelas[n] for n in nomes(r"^const TABELAS = \[(.*?)\];") if n in tabelas]
    fechadas = {pid for n in nomes(r"^const TABELAS_FECHADAS = new Set\(\[(.*?)\]\);") for pid in tabelas.get(n, {})}
    megas: dict = {}
    for n in nomes(r"export function golpesDaPlanilhaDaMega\(pokeId\) \{(.*?)return"):  # a 1ª tabela que tem vence
        for pid, golpes in tabelas.get(n, {}).items():
            megas.setdefault(pid, golpes)
    return ordem, fechadas, megas


def baixar_catalogo() -> int:
    """Baixa os catálogos públicos de espécies (4 arquivos + as correções) e grava só o que a caça usa.

    Por espécie: nome, tipos, os seis stats-base e os golpes (poder, tipo, físico?, recarga, nível).
    As correções (`creatures-audit-overrides.json`) trocam stats-base e golpes, como no cliente do jogo.
    """
    especies: dict[int, dict] = {}
    outland: set[int] = set()
    for nome in CATALOGOS:
        for c in (_baixar(nome) or {}).get("creatures") or []:
            especies.setdefault(int(c["pokeId"]), c)
            if "outland" in nome:
                outland.add(int(c["pokeId"]))
        time.sleep(1)
    outland |= {pid for pid in especies if pid in FANTASMA_OUTLAND}
    for o in (_baixar(OVERRIDES) or {}).get("overrides") or []:
        c = especies.get(int(o.get("pokeId", -1)))
        if not c:
            continue
        for k in ("baseHp", "baseAtk", "baseDef", "baseSpAtk", "baseSpDef", "baseSpeed"):
            if isinstance(o.get(k), (int, float)):
                c[k] = o[k]
        if isinstance(o.get("attacks"), list):
            c["attacks"] = o["attacks"]
    # Os golpes das planilhas de balanceamento substituem os do catálogo (aplicarGolpesDasPlanilhas do jogo).
    ordem, fechadas, megas = ler_planilhas(_baixar_texto(URL_PLANILHAS))
    for tabela in ordem:
        for pid, golpes in tabela.items():
            if pid in especies:
                especies[pid]["attacks"] = [dict(g) for g in golpes]
                especies[pid]["golpesFechados"] = pid in fechadas
    # A árvore de evolução, montada como o cliente monta (analise/evolucao.py). Se os módulos falharem, o
    # catálogo sai do mesmo jeito, só sem as evoluções (a análise de evolução avisa).
    from analise import evolucao
    try:
        time.sleep(1)
        for p in (_baixar(SPRITES_LAB) or {}).get("patches") or []:
            c = especies.get(int(p.get("pokeId", -1)))
            if c and p.get("looktype"):
                c["looktype"] = p["looktype"]
        js = []
        for nome in MODULOS_EVOLUCAO:
            time.sleep(1)
            js.append(_baixar_texto(URL_SHARED + nome))
        tabelas = evolucao.ler_tabelas(*js)
    except Exception as e:  # noqa: BLE001
        print(f"catálogo: sem a árvore de evolução ({e!r})", flush=True)
        tabelas = None
    if tabelas:
        evolucao.arvore_antes_dos_golpes(especies, tabelas)
    for c in especies.values():
        injetar_golpes_600(c)
    if tabelas:
        evolucao.arvore_depois_dos_golpes(especies, tabelas, outland)
    saida = {}
    for pid, c in especies.items():
        saida[pid] = {
            "n": c.get("name"), "t": [x for x in (c.get("type1"), c.get("type2")) if x],
            "b": [c.get(k) or 0 for k in ("baseHp", "baseAtk", "baseDef", "baseSpAtk", "baseSpDef", "baseSpeed")],
            "g": [[a.get("power") or 0, a.get("type"), 0 if a.get("category") == "SPECIAL" else 1,
                   a.get("cooldownMs") or 0, a.get("learnLevel") or 1] for a in c.get("attacks") or []],
        }
        if tabelas:
            if not evolucao.tem_arte(c, outland, especies):
                saida[pid]["a"] = 0
            ds = evolucao.destinos(c, especies, tabelas)
            if ds:
                saida[pid]["e"] = ds
    # Megas com moveset próprio (planilha das megas): os stats-base vêm da forma base; os tipos, do anúncio.
    for pid, golpes in megas.items():
        base = saida.get(pid % 1000)
        if base and pid not in saida:
            saida[pid] = {**{k: v for k, v in base.items() if k not in ("e", "a")}, "n": f"Mega {base['n']}", "mega": True,
                          "g": [[g["power"], g["type"], 0 if g["category"] == "SPECIAL" else 1, g["cooldownMs"], 1] for g in golpes]}
    caminhos.JOGO.mkdir(parents=True, exist_ok=True)
    _gravar_json(caminhos.CATALOGO_JOGO, {"salvo_ms": int(time.time() * 1000), "especies": saida,
                                          "pedras": (tabelas or {}).get("pedras") or {}})
    return len(saida)


# ---------------------------------------------------------------- o motor

class SemDados(Exception):
    pass


class Motor:
    """Catálogo + hunts carregados uma vez; `xp_h()` avalia um Pokémon em microssegundos a milissegundos."""

    def __init__(self, catalogo: dict, welcome: dict):
        self.esp = {int(k): v for k, v in catalogo["especies"].items()}
        self.pedras = catalogo.get("pedras") or {}       # tipo → nome da pedra de evolução
        self.tem_evolucoes = any("e" in v for v in self.esp.values())
        c = {**PADRAO_CONSTS, **(welcome.get("consts") or {})}
        self.ampl, self.mult_hp, self.mult_dano = c["ampliacaoHunt"], c["multHpSelvagem"], c["multDanoSelvagem"]
        self.shiny_stone_custo = c.get("shinyStoneCusto")   # None até o robô entrar com esta versão
        self.tabela = welcome.get("tabelaTipos") or _tabela_padrao()
        self._ef: dict = {}
        self.hunts = []
        for h in welcome.get("hunts") or []:
            n = int(h.get("nivel") or 1)
            mobs, total = [], 0
            for e in h.get("especies") or []:
                esp, pts = self.esp.get(int(e.get("pokeId", -1))), float(e.get("pontos") or 0)
                if not esp or pts <= 0:
                    continue
                b = esp["b"]
                st = [(x + 2 * IV_SELVAGEM) * n / 100 for x in b]
                hps = [max(HP_COMBATE_MIN, round((b[0] + 2 * iv) * n / 100 * HP_COMBATE_MULT)) * self.mult_hp
                       for iv in IVS_HP_AMOSTRA]
                golpes = [g for g in esp["g"] if g[4] <= n]
                mobs.append({"w": pts, "t": esp["t"], "st": st, "hps": hps, "golpes": golpes,
                             "d_min": max(1, min(st[2], st[4])), "hp_medio": sum(hps) / len(hps)})
                total += pts
            if not mobs:
                continue
            for m in mobs:
                m["w"] /= total
            self.hunts.append({"slug": h.get("slug"), "nome": h.get("nome") or h.get("slug"), "nivel": n,
                               "xp": xp_do_nivel(n), "mobs": mobs})
        self.hunts.sort(key=lambda h: -h["nivel"])

    # -- tipos
    def ef(self, atq: str, defesa: list) -> float:
        k = (atq, tuple(defesa))
        v = self._ef.get(k)
        if v is None:
            linha = self.tabela.get(atq, {})
            v = 1.0
            for d in dict.fromkeys(defesa[:2]):
                v *= DIAGONAL.get(atq, 1) if d == atq else linha.get(d, 1)
            if v not in (0, 1):  # a caça amplia a vantagem e a desvantagem
                v = 1 + (v - 1) * self.ampl if v > 1 else v / self.ampl
            self._ef[k] = v
        return v

    def especie(self, species_id: int, tipos: list | None = None) -> dict | None:
        e = self.esp.get(int(species_id or 0))
        if e is not None and e.get("mega") and tipos:
            e = {**e, "t": list(tipos)}
        if e is None and species_id and species_id >= 3000:
            # Mega (3006, 9006 → 6): os golpes da forma base mais o golpe de mega (poder 600, 30 s), do 1º
            # tipo da mega e no lado de ataque mais forte dela (shared/megas.mjs).
            base = self.esp.get(int(species_id) % 1000)
            if base:
                t = (tipos or base["t"])[0]
                fis = 1 if base["b"][1] >= base["b"][3] else 0
                e = {**base, "t": list(tipos or base["t"]), "g": base["g"] + [[600, t, fis, GOLPE_MEGA_CD_MS, 1]]}
        return e

    # -- a conta
    def xp_h(self, species_id, nivel, stats: dict, ivs: dict | None, tipos: list | None,
             nivel_treinador: int | None = None) -> dict | None:
        esp = self.especie(species_id, tipos)
        if not esp or not nivel or not stats:
            return None
        L = int(nivel)
        tipos = list(tipos or esp["t"])
        atk, spa = stats.get("atk") or 1, stats.get("spAtk") or 1
        dfs, spd_ = stats.get("def") or 1, stats.get("spDef") or 1
        hp_pk = max(HP_COMBATE_MIN, round((stats.get("hp") or 1) * HP_COMBATE_MULT))
        iv_spd = min(32, max(1, int((ivs or {}).get("speed") or 1)))
        gap = max(PISO_CD_S, GAP_S - iv_spd * S_POR_IV_SPD)
        cd_inv = max(PISO_CD_S, INVESTIDA_CD_S - iv_spd * S_POR_IV_SPD)
        base_spd = esp["b"][5]
        pot_spd = min(7.0, base_spd / 20 if base_spd <= 120 else 6 + (base_spd - 120) / 40)
        desc = 1 - pot_spd * (iv_spd / 32) / 100
        golpes = [(max(PODER_MINIMO, p), t, f, round(cd * desc) / 1000) for p, t, f, cd, ll in esp["g"] if ll <= L]
        fator_nivel = 2 * L / 5 + 2
        teto_kph = 3600 / S_POR_ABATE_MAPA
        # Teto do dano de um golpe contra qualquer selvagem: o golpe mais forte, com STAB e a maior
        # efetividade possível. Serve para descartar uma hunt sem simular.
        k_teto = fator_nivel * max([INVESTIDA_PODER] + [g[0] for g in golpes]) * max(atk, spa)
        fator_teto = STAB * EF_MAXIMA * RAND_MEDIO

        # Os golpes contra cada combinação de tipos do selvagem (poder × STAB × efetividade), calculados uma vez
        # por anúncio: há poucas combinações e elas se repetem em muitas hunts.
        por_tipos: dict = {}
        args = (golpes, tipos, fator_nivel, atk, spa, dfs, spd_, hp_pk, gap, cd_inv, por_tipos)
        # 1) Estimativa barata em todas as hunts liberadas, da mais alta para a mais baixa; guarda as
        #    CANDIDATAS melhores. Para quando nem o teto de uma hunt (abates/h
        #    máximos × XP do abate) alcança a pior das guardadas.
        cands: list = []                    # heap de (estimativa, ordem, hunt)
        for n_h, h in enumerate(self.hunts):
            if nivel_treinador and h["nivel"] > nivel_treinador:
                continue
            if len(cands) >= CANDIDATAS and teto_kph * h["xp"] <= cands[0][0]:
                break
            if any(max(m["hps"]) / (((k_teto / m["d_min"]) / 50 + 2) * fator_teto) > MAX_GOLPES_POR_ABATE for m in h["mobs"]):
                continue                    # não mata nem com o golpe mais forte e a melhor vantagem de tipo
            est = self._estimar(h, *args)
            if est is None:
                continue
            if len(cands) < CANDIDATAS:
                heapq.heappush(cands, (est, n_h, h))
            elif est > cands[0][0]:
                heapq.heapreplace(cands, (est, n_h, h))
        # 2) A mini-luta só nas candidatas: é ela que dá o número.
        melhor = None
        for _est, _n, h in cands:
            r = self._hunt(h, *args)
            if r and (melhor is None or r["xp_h"] > melhor["xp_h"]):
                melhor = r
        return melhor

    def _golpes_contra(self, golpes, tipos, mt, por_tipos):
        chave = tuple(mt)
        v = por_tipos.get(chave)
        if v is None:
            qs = []
            for p, tg, fis, cd in golpes:
                e = self.ef(tg, mt)
                if e > 0:
                    mult = (STAB if tg in tipos else 1) * e * RAND_MEDIO
                    qs.append((p * mult, fis, cd, 2 * mult))   # dano = k·q + extra
            t_inv = tipos[1] if len(tipos) > 1 and self.ef(tipos[0], mt) == 0 else tipos[0]
            m_inv = STAB * self.ef(t_inv, mt) * RAND_MEDIO
            # Somas para as contas fechadas (abertura: todos os golpes uma vez; ritmo: cada um por recarga),
            # separadas em físico e especial para multiplicar pelo ATK/DEF ou SP.ATK/SP.DEF de cada selvagem.
            soma = [0.0] * 6   # abertura físico, especial, extra; ritmo físico, especial, extra
            for q, fis, cd, extra in qs:
                soma[0 if fis else 1] += q
                soma[2] += extra
                if cd > 0:
                    soma[3 if fis else 4] += q / cd
                    soma[5] += extra / cd
            v = por_tipos[chave] = (qs, INVESTIDA_PODER * m_inv, 2 * m_inv, soma)
        return v

    def _estimar(self, h, golpes, tipos, fator_nivel, atk, spa, dfs, spd_, hp_pk, gap, cd_inv, por_tipos):
        """XP/h estimado sem simular, pela média de longo prazo da caça. Por abate, cada golpe sai
        (luta + caminhada) ÷ recarga vezes (a recarga corre também entre um abate e outro) e a Investida sai
        1 + luta ÷ passo vezes. Igualando o dano ao HP médio do selvagem, a luta sai de uma conta de 1º grau:
        luta = (HP − Investida − caminhada·ritmo dos golpes) ÷ (ritmo dos golpes + Investida ÷ passo).
        Não conta as mortes; a mini-luta das candidatas conta."""
        luta = 0.0
        for m in h["mobs"]:
            st = m["st"]
            _qs, q_inv, extra_inv, soma = self._golpes_contra(golpes, tipos, m["t"], por_tipos)
            k_fis, k_esp = fator_nivel * atk / max(1, st[2]) / 50, fator_nivel * spa / max(1, st[4]) / 50
            d_inv = k_fis * q_inv + extra_inv
            abertura = k_fis * soma[0] + k_esp * soma[1] + soma[2] + d_inv
            ritmo = k_fis * soma[3] + k_esp * soma[4] + soma[5] + d_inv / max(gap, cd_inv)
            if ritmo <= 0 or (max(m["hps"]) - abertura) / ritmo > MAX_LUTA_S:
                return None
            ritmo_golpes = ritmo - d_inv / max(gap, cd_inv)
            luta += m["w"] * max(0.0, (m["hp_medio"] - d_inv - S_POR_ABATE_MAPA * ritmo_golpes) / ritmo)
        return h["xp"] * 3600 / (tempo_morto(S_POR_ABATE_MAPA, luta) + luta)

    def _hunt(self, h, golpes, tipos, fator_nivel, atk, spa, dfs, spd_, hp_pk, gap, cd_inv, por_tipos):
        """XP/h numa hunt pela mini-luta, ou None se ele não mata."""
        luta = dps = hit_max = 0.0
        por_mob = []
        for m in h["mobs"]:
            st, mt = m["st"], m["t"]
            # nossos golpes contra este selvagem: dano = (fator·A/D/50)·q + extra, com q = poder·STAB·ef·rolagem
            qs, q_inv, extra_inv, soma = self._golpes_contra(golpes, tipos, mt, por_tipos)
            k_fis, k_esp = fator_nivel * atk / max(1, st[2]) / 50, fator_nivel * spa / max(1, st[4]) / 50
            d_inv = k_fis * q_inv + extra_inv
            # Limite fechado, sem simular: em F segundos cada golpe sai no máximo 1 + F/recarga vezes e a Investida
            # 1 + F/passo. Então dano(F) ≤ abertura + ritmo·F, e a luta dura pelo menos (HP − abertura) ÷ ritmo.
            abertura = k_fis * soma[0] + k_esp * soma[1] + soma[2] + d_inv
            ritmo = k_fis * soma[3] + k_esp * soma[4] + soma[5] + d_inv / max(gap, cd_inv)
            if ritmo <= 0 or (max(m["hps"]) - abertura) / ritmo > MAX_LUTA_S:
                return None                 # não mata nem no melhor caso
            por_mob.append((m, qs, k_fis, k_esp, d_inv))
        for m, qs, k_fis, k_esp, d_inv in por_mob:
            st, mt = m["st"], m["t"]
            gs = [((k_fis if fis else k_esp) * q + extra, cd) for q, fis, cd, extra in qs]
            s = _segundos_por_abate(gs, d_inv, cd_inv, gap, m["hps"], S_POR_ABATE_MAPA)
            if s is None:
                return None
            luta += m["w"] * s
            # o que ele faz com a gente
            fn_mob = 2 * h["nivel"] / 5 + 2
            danos = []
            for p, tg, fis, _cd, _ll in m["golpes"]:
                a, d = (st[1], dfs) if fis else (st[3], spd_)
                danos.append(((fn_mob * max(PODER_MINIMO, p) * a / max(1, d)) / 50 + 2)
                             * (STAB if tg in mt else 1) * self.ef(tg, tipos) * RAND_MEDIO)
            ti = mt[1] if len(mt) > 1 and self.ef(mt[0], tipos) == 0 else mt[0]
            inv = ((fn_mob * INVESTIDA_PODER * st[1] / max(1, dfs)) / 50 + 2) * STAB * self.ef(ti, tipos) * RAND_MEDIO
            media = (sum(danos) / len(danos)) * 0.92 + inv * 0.08 if danos else inv
            dps += m["w"] * media * self.mult_dano / GAP_SELVAGEM_S
            hit_max = max(hit_max, max([inv] + danos) / RAND_MEDIO * self.mult_dano)
        s_abate = tempo_morto(S_POR_ABATE_MAPA, luta) + luta
        kph = 3600 / s_abate
        um_hit = hit_max >= hp_pk
        uptime = 1.0
        if um_hit:                          # com poção, só morre quem leva o HP inteiro de um golpe
            vida_s = hp_pk / hit_max * s_abate
            uptime = vida_s / (vida_s + MORTE_S)
        kph *= uptime
        return {"xp_h": kph * h["xp"], "kph": kph, "hunt": h["nome"], "slug": h["slug"], "nivel_hunt": h["nivel"],
                "luta_s": round(luta, 2), "morre": um_hit}


def _segundos_por_abate(golpes, d_inv, cd_inv, gap, hps, morto):
    """Luta média por abate: a cada `gap`, o golpe pronto de maior dano; sem golpe, a Investida."""
    ordem = sorted((g for g in golpes if g[0] > 0), key=lambda g: -g[0])
    pronto = [0.0] * len(ordem)
    prox_inv = t = luta = 0.0
    for hp in hps:
        feito, ini, ultimo, n = 0.0, t, t, 0
        while feito < hp:
            if n >= MAX_GOLPES_POR_ABATE:
                return None
            n += 1
            for j, (d, cd) in enumerate(ordem):
                if pronto[j] <= t:
                    feito += d
                    pronto[j] = t + cd
                    break
            else:
                if prox_inv <= t:
                    # Só Investida até o próximo golpe ficar pronto (ou o selvagem cair): salta o trecho
                    # inteiro de uma vez. As Investidas saem a cada máx(gap, recarga); um golpe que fica
                    # pronto no mesmo instante de uma Investida tem a preferência.
                    passo = max(gap, cd_inv)
                    t_golpe = min(pronto) if pronto else math.inf
                    k = math.ceil((hp - feito) / d_inv) if d_inv > 0 else MAX_GOLPES_POR_ABATE + 1
                    if t_golpe < math.inf:
                        k = max(1, min(k, math.ceil((t_golpe - t) / passo)))
                    if n - 1 + k > MAX_GOLPES_POR_ABATE:
                        return None
                    n += k - 1
                    feito += k * d_inv
                    t += (k - 1) * passo
                    prox_inv = t + cd_inv
                else:
                    t = min([prox_inv] + pronto)
                    n -= 1          # esperar não é golpe
                    continue
            ultimo = t
            t += gap
        luta += ultimo - ini
        t = ultimo + morto
    return luta / len(hps)


def _tabela_padrao() -> dict:
    """Sem a tabela do welcome: a da série (a mesma de analise/pvp.py), no formato do jogo."""
    from analise import pvp
    return {a: {d: v for d, v in linha.items() if v != 1.0 and d != a} for a, linha in pvp.TABELA.items()}


_motor: tuple | None = None   # (marcas dos arquivos, Motor)
_cache: dict = {}             # (id do anúncio, nível do treinador) → resultado; o anúncio não muda


def xp_do_anuncio(m: Motor, anuncio_id, species_id, nivel, stats, ivs, tipos, nivel_treinador=None) -> dict | None:
    """`Motor.xp_h` de um anúncio da loja (stats, IVs e tipos como estão em pk_anuncios), com cache."""
    chave = (anuncio_id, nivel_treinador)
    if chave not in _cache:
        if len(_cache) > 200_000:
            _cache.clear()
        js = lambda v, p: json.loads(v) if isinstance(v, str) and v else (v or p)  # noqa: E731
        _cache[chave] = m.xp_h(species_id, nivel, js(stats, {}), js(ivs, {}), js(tipos, []), nivel_treinador)
    return _cache[chave]


def motor() -> Motor:
    """O motor com os arquivos de data/jogo/, recarregado só quando eles mudam."""
    global _motor
    try:
        marca = (caminhos.CATALOGO_JOGO.stat().st_mtime, caminhos.WELCOME_JOGO.stat().st_mtime)
    except OSError:
        raise SemDados("sem os dados do jogo ainda: o robô baixa o catálogo e guarda as hunts no próximo login")
    if _motor is None or _motor[0] != marca:
        cat = json.loads(caminhos.CATALOGO_JOGO.read_text(encoding="utf-8"))
        wel = json.loads(caminhos.WELCOME_JOGO.read_text(encoding="utf-8"))
        _motor = (marca, Motor(cat, wel))
        _cache.clear()              # dados do jogo novos: as contas antigas não valem mais
    return _motor[1]
