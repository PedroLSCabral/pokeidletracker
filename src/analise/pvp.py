"""PvP: o seu histórico, o meta e as compras que mais ajudam o seu time.

Os dados vêm do Tracker público do jogo (`https://pokeidle.io/tracker`, rotas `/tracker/api/*` em
JSON). É o mesmo site que o botão "Tracker" do PvP abre. Não precisa de login, então nada disso
toca nas suas contas (nem derruba o Idle Deck). Cada resposta fica num cache no banco
(`pvp_cache`), e os pedidos saem com pelo menos 1,5 s entre eles. O site avisa quando alguém pede
rápido demais, e o cache segura a página nesse caso.

A análise, para um nick:
  1. O seu time: as espécies das suas últimas partidas.
  2. As ameaças: para quem você mais perde (os "counters" que o Tracker calcula para você), mais os
     pokémons que mais te bateram nas derrotas recentes.
  3. Os tipos que te castigam e os buracos do time, pela tabela de tipos da série (a mesma do jogo,
     `shared/tipo-efetividade.mjs`).
  4. As respostas: para cada ameaça, quem mais ganha dela no PvP inteiro (a página da espécie no
     Tracker), somado ao meta do seu rank e ao encaixe de tipos.
  5. A loja: os anúncios dessas espécies que cabem no orçamento.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

API = "https://pokeidle.io/tracker/api/"
USER_AGENT = "Mozilla/5.0 (pokeidletracker painel)"
PAUSA_S = 1.5
TTL_S = {"jogador": 5 * 60, "partidas": 5 * 60, "pokemon": 12 * 3600, "meta": 6 * 3600,
         "ladder": 6 * 3600, "inicio": 6 * 3600}
TTL_OUTRO_JOGADOR_S = 6 * 3600     # o perfil de quem está no topo muda pouco: 6 h de cache
FAIXAS = ("todas", "baixo", "alto", "bronze", "prata", "ouro", "platina", "diamante", "mestre")
TIER_PARA_FAIXA = {"bronze": "bronze", "prata": "prata", "ouro": "ouro", "platina": "platina",
                   "diamante": "diamante", "mestre": "mestre", "graomestre": "mestre", "challenger": "mestre"}
MAX_AMEACAS = 5
MIN_CONFRONTOS = 20        # confrontos mínimos para "X ganha de Y" contar
TOP_JOGADORES = 10
NOMES_TIPO = {"NORMAL": "Normal", "FIRE": "Fogo", "WATER": "Água", "GRASS": "Planta", "ELECTRIC": "Elétrico",
              "ICE": "Gelo", "FIGHTING": "Lutador", "POISON": "Veneno", "GROUND": "Terra", "FLYING": "Voador",
              "PSYCHIC": "Psíquico", "BUG": "Inseto", "ROCK": "Pedra", "GHOST": "Fantasma", "DRAGON": "Dragão",
              "DARK": "Sombrio", "STEEL": "Aço", "FAIRY": "Fada"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pvp_cache (
    chave TEXT PRIMARY KEY,   -- rota + parâmetros
    ms    INTEGER NOT NULL,   -- quando foi buscado
    json  TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- tabela de tipos (a da série)

TIPOS = list(NOMES_TIPO)
_SE = {  # atacante: tipos em que ele dá ×2
    "FIRE": "GRASS ICE BUG STEEL", "WATER": "FIRE GROUND ROCK", "GRASS": "WATER GROUND ROCK",
    "ELECTRIC": "WATER FLYING", "ICE": "GRASS GROUND FLYING DRAGON", "FIGHTING": "NORMAL ICE ROCK DARK STEEL",
    "POISON": "GRASS FAIRY", "GROUND": "FIRE ELECTRIC POISON ROCK STEEL", "FLYING": "GRASS FIGHTING BUG",
    "PSYCHIC": "FIGHTING POISON", "BUG": "GRASS PSYCHIC DARK", "ROCK": "FIRE ICE FLYING BUG",
    "GHOST": "PSYCHIC GHOST", "DRAGON": "DRAGON", "DARK": "PSYCHIC GHOST", "STEEL": "ICE ROCK FAIRY",
    "FAIRY": "FIGHTING DRAGON DARK",
}
_NVE = {  # atacante: tipos em que ele dá ×0,5
    "NORMAL": "ROCK STEEL", "FIRE": "FIRE WATER ROCK DRAGON", "WATER": "WATER GRASS DRAGON",
    "GRASS": "FIRE GRASS POISON FLYING BUG DRAGON STEEL", "ELECTRIC": "ELECTRIC GRASS DRAGON",
    "ICE": "FIRE WATER ICE STEEL", "FIGHTING": "POISON FLYING PSYCHIC BUG FAIRY",
    "POISON": "POISON GROUND ROCK GHOST", "GROUND": "GRASS BUG", "FLYING": "ELECTRIC ROCK STEEL",
    "PSYCHIC": "PSYCHIC STEEL", "BUG": "FIRE FIGHTING POISON FLYING GHOST STEEL FAIRY",
    "ROCK": "FIGHTING GROUND STEEL", "GHOST": "DARK", "DRAGON": "STEEL", "DARK": "FIGHTING DARK FAIRY",
    "STEEL": "FIRE WATER ELECTRIC STEEL", "FAIRY": "FIRE POISON STEEL",
}
_IMUNE = {"NORMAL": "GHOST", "ELECTRIC": "GROUND", "FIGHTING": "GHOST", "POISON": "STEEL", "GROUND": "FLYING",
          "PSYCHIC": "DARK", "GHOST": "NORMAL", "DRAGON": "FAIRY"}
TABELA = {a: {d: 1.0 for d in TIPOS} for a in TIPOS}
for _a, _ds in _SE.items():
    for _d in _ds.split():
        TABELA[_a][_d] = 2.0
for _a, _ds in _NVE.items():
    for _d in _ds.split():
        TABELA[_a][_d] = 0.5
for _a, _ds in _IMUNE.items():
    for _d in _ds.split():
        TABELA[_a][_d] = 0.0


def mult(atq: str, defesa: list[str]) -> float:
    """Multiplicador de um golpe do tipo `atq` contra um defensor com até 2 tipos."""
    v = 1.0
    for d in dict.fromkeys(defesa[:2]):
        v *= TABELA.get(atq, {}).get(d, 1.0)
    return v


def melhor_ataque(atacante: list[str], defensor: list[str]) -> float:
    """O melhor golpe de mesmo tipo (STAB) do atacante contra o defensor."""
    return max((mult(t, defensor) for t in atacante[:2]), default=1.0)


# ---------------------------------------------------------------- Tracker (com cache)

class ErroPvP(Exception):
    pass


_trava = threading.Lock()
_ultimo_pedido = 0.0
MENSAGENS = {"semJogador": "nenhum treinador com esse nick no Tracker",
             "nickInvalido": "nick inválido (3 a 20 letras, números ou _)",
             "muitasRequisicoes": "o Tracker pediu para esperar um minuto (pedidos rápidos demais)"}


def preparar(con) -> None:
    con.executescript(SCHEMA)


def tracker(con, rota: str, ttl_s: float | None = None, **params) -> dict:
    """GET /tracker/api/<rota>, com cache no banco. Se o site falhar e houver uma cópia velha, usa a velha."""
    preparar(con)
    params = {k: v for k, v in params.items() if v not in (None, "")}
    chave = rota + "?" + urllib.parse.urlencode(sorted(params.items()))
    ttl = TTL_S.get(rota, 3600) if ttl_s is None else ttl_s
    agora = time.time()
    r = con.execute("SELECT ms, json FROM pvp_cache WHERE chave = ?", (chave,)).fetchone()
    if r and agora - r[0] / 1000 < ttl:
        return json.loads(r[1])
    global _ultimo_pedido
    with _trava:
        espera = _ultimo_pedido + PAUSA_S - time.time()
        if espera > 0:
            time.sleep(espera)
        url = API + rota + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                dados = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                erro = str(json.loads(e.read()).get("erro", "")).replace("tracker.", "")
            except Exception:
                erro = ""
            if r and e.code >= 429:
                return json.loads(r[1]) | {"_velho": True}
            raise ErroPvP(MENSAGENS.get(erro, f"o Tracker respondeu {e.code} {erro}".strip())) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if r:
                return json.loads(r[1]) | {"_velho": True}
            raise ErroPvP("o Tracker do jogo não respondeu") from None
        finally:
            _ultimo_pedido = time.time()
    con.execute("INSERT OR REPLACE INTO pvp_cache (chave, ms, json) VALUES (?,?,?)",
                (chave, int(agora * 1000), json.dumps(dados, ensure_ascii=False)))
    con.commit()
    return dados


def atualizar_meta(con) -> None:
    """Pré-carga para a aba abrir rápido (o robô chama a cada 6 h): o meta das faixas largas, o topo do
    ranking e os times de quem está no topo. São ~14 pedidos, com 1,5 s entre eles."""
    for faixa in ("todas", "alto", "mestre"):
        tracker(con, "meta", ordem="uso", limite=200, faixa="" if faixa == "todas" else faixa)
    lad = tracker(con, "ladder", pagina=0, limite=50)
    for j in (lad.get("linhas") or [])[:TOP_JOGADORES]:
        try:
            tracker(con, "jogador", ttl_s=TTL_OUTRO_JOGADOR_S, nick=j["nick"])
        except ErroPvP:
            pass


# ---------------------------------------------------------------- análise

def _tipos_conhecidos(*listas) -> dict[int, list[str]]:
    out = {}
    for lista in listas:
        for x in lista or []:
            if x.get("id") is not None and x.get("tipos"):
                out[int(x["id"])] = list(x["tipos"])
    return out


def _nota_meta(linha: dict | None, peso: int = 200) -> float:
    """Taxa de vitória puxada para 50% quando há poucas partidas (encolhimento bayesiano)."""
    if not linha:
        return 0.5
    return (linha.get("vitorias", 0) + 0.5 * peso) / (linha.get("partidas", 0) + peso)


def _time_atual(partidas: list[dict], n: int = 5) -> list[dict]:
    """As espécies que mais apareceram nas últimas 5 partidas: é o time que você está usando agora."""
    cont, info, ultima = Counter(), {}, {}
    for i, p in enumerate(partidas[:5]):
        for pk in (p.get("eu") or {}).get("pks") or []:
            cont[pk["id"]] += 1
            info.setdefault(pk["id"], pk)
            ultima.setdefault(pk["id"], i)
    ids = sorted(cont, key=lambda k: (-cont[k], ultima[k]))[:n]
    return [{"id": k, "nome": info[k]["nome"], "nivel": info[k].get("nivel"), "shiny": bool(info[k].get("shiny")),
             "aparicoes": cont[k]} for k in ids]


def _ameacas(perfil: dict, partidas: list[dict]) -> list[dict]:
    """Para quem você perde: os counters da temporada (derrotas) + quem mais te bateu nas derrotas recentes."""
    pts: dict[int, dict] = {}
    for c in perfil.get("counters") or []:
        derrotas = c["partidas"] - c["vitorias"]
        pts[c["id"]] = {"id": c["id"], "nome": c["nome"], "tipos": c.get("tipos") or [], "partidas": c["partidas"],
                        "derrotas": derrotas, "taxa": c["winrate"], "dano_recente": 0, "derrotas_recentes": 0}
    for p in partidas:
        if p.get("venci"):
            continue
        for pk in (p.get("ele") or {}).get("pks") or []:
            a = pts.setdefault(pk["id"], {"id": pk["id"], "nome": pk["nome"], "tipos": [], "partidas": 0, "derrotas": 0,
                                          "taxa": None, "dano_recente": 0, "derrotas_recentes": 0})
            a["dano_recente"] += pk.get("dano") or 0
            a["derrotas_recentes"] += 1
    if not pts:
        return []
    max_dano = max(a["dano_recente"] for a in pts.values()) or 1
    for a in pts.values():
        # Peso: derrotas da temporada + as recentes (que dizem mais do time de agora), com o dano dando o desempate.
        a["peso"] = a["derrotas"] + 3 * a["derrotas_recentes"] + 5 * a["dano_recente"] / max_dano
    return sorted(pts.values(), key=lambda a: -a["peso"])[:MAX_AMEACAS]


def _buracos(time_tipos: list[list[str]]) -> list[dict]:
    """Por tipo de ataque: quantos do time sofrem ×2 ou mais e quantos resistem."""
    out = []
    for atq in TIPOS:
        ms = [mult(atq, t) for t in time_tipos if t]
        fracos = sum(1 for m in ms if m >= 2)
        resistem = sum(1 for m in ms if m <= 0.5)
        out.append({"tipo": atq, "nome": NOMES_TIPO[atq], "fracos": fracos, "resistem": resistem})
    return sorted(out, key=lambda x: (-(x["fracos"] - x["resistem"]), -x["fracos"]))


def analisar(con, nick: str, faixa: str = "", orcamento: float | None = None, moeda: str = "gems",
             limite: int = 30) -> dict:
    nick = nick.strip()
    if not nick:
        raise ErroPvP("falta o nick")
    perfil = tracker(con, "jogador", nick=nick)
    partidas = perfil.get("partidas") or []
    rank = perfil.get("rank") or {}
    if faixa not in FAIXAS:  # sem escolha: o rank do próprio jogador
        faixa = TIER_PARA_FAIXA.get(rank.get("tierId") or "", "todas")
    meta = tracker(con, "meta", ordem="uso", limite=200, faixa="" if faixa == "todas" else faixa)
    meta_por_id = {int(x["id"]): x for x in meta.get("linhas") or []}

    time_ = _time_atual(partidas)
    ameacas = _ameacas(perfil, partidas)
    tipos = _tipos_conhecidos(meta.get("linhas"), perfil.get("pokemons"), perfil.get("counters"), perfil.get("vitimas"))
    meus = {int(x["id"]): x for x in perfil.get("pokemons") or []}
    for pk in time_:
        pk["tipos"] = tipos.get(pk["id"], [])
        m = meus.get(pk["id"])
        pk["taxa"] = m["winrate"] if m else None
        pk["partidas"] = m["partidas"] if m else None
        pk["meta"] = _nota_meta(meta_por_id[pk["id"]]) if pk["id"] in meta_por_id else None  # fora dos 200 mais usados
    for a in ameacas:
        a["tipos"] = a["tipos"] or tipos.get(a["id"], [])
        # Quem do seu time sofre e quem resiste aos golpes de mesmo tipo dessa ameaça.
        a["sofrem"] = [pk["nome"] for pk in time_ if pk["tipos"] and melhor_ataque(a["tipos"], pk["tipos"]) >= 2]
        a["resistem"] = [pk["nome"] for pk in time_ if pk["tipos"] and melhor_ataque(a["tipos"], pk["tipos"]) <= 0.5]
    buracos = _buracos([pk["tipos"] for pk in time_])

    # ---- tipos que mais te castigam (os das ameaças, pelo peso de cada uma)
    peso_tipo = Counter()
    for a in ameacas:
        for t in a["tipos"][:2]:
            peso_tipo[t] += a["peso"]
    tot = sum(peso_tipo.values()) or 1
    tipos_castigam = [{"tipo": t, "nome": NOMES_TIPO.get(t, t), "parte": round(v / tot * 100)}
                      for t, v in peso_tipo.most_common(4)]

    # ---- respostas: quem ganha das suas ameaças no PvP inteiro
    cand: dict[int, dict] = defaultdict(lambda: {"resp": 0.0, "venceu": []})
    peso_total = sum(a["peso"] for a in ameacas) or 1
    for a in ameacas:
        try:
            pag = tracker(con, "pokemon", id=a["id"], faixa="" if faixa == "todas" else faixa)
        except ErroPvP:
            continue
        a["tipos"] = a["tipos"] or (pag.get("pokemon") or {}).get("tipos") or []
        for c in pag.get("counters") or []:
            n = c.get("partidas") or 0
            if n < MIN_CONFRONTOS:
                continue
            ganha = 1 - c["winrate"]          # a taxa da lista é a da ameaça contra ele
            confianca = n / (n + 60)          # 100% em 20 partidas não vale o mesmo que 70% em 2.000
            k = int(c["id"])
            tipos.setdefault(k, c.get("tipos") or [])
            cand[k]["resp"] += (a["peso"] / peso_total) * (ganha - 0.5) * 2 * confianca
            cand[k]["venceu"].append({"nome": a["nome"], "taxa": round(ganha, 3), "partidas": n})
            cand[k]["nome"] = c["nome"]

    # O meta do rank também entra: as espécies com boa taxa e amostra decente.
    for k, linha in meta_por_id.items():
        if linha.get("partidas", 0) >= 200 and _nota_meta(linha) > 0.5:
            cand[k]["nome"] = linha["nome"]

    no_time = {pk["id"] for pk in time_}
    lista = []
    for k, c in cand.items():
        if k in no_time or not c.get("nome"):
            continue
        tk = tipos.get(k, [])
        # Encaixe de tipos: resiste aos golpes das ameaças? Bate forte nelas? Tapa os buracos do time?
        encaixe = 0.0
        for a in ameacas:
            if not a["tipos"] or not tk:
                continue
            w = a["peso"] / peso_total
            d = melhor_ataque(a["tipos"], tk)
            encaixe += w * (1 if d <= 0.5 else -1 if d >= 2 else 0)
            encaixe += w * (0.5 if melhor_ataque(tk, a["tipos"]) >= 2 else 0)
        tampa = [b["nome"] for b in buracos[:3] if b["fracos"] >= 2 and tk and mult(b["tipo"], tk) <= 0.5]
        encaixe += 0.15 * len(tampa)
        m = meta_por_id.get(k)
        nota_meta = _nota_meta(m)
        pontos = 0.45 * c["resp"] + 0.35 * (nota_meta - 0.5) * 6 + 0.20 * encaixe
        lista.append({"id": k, "nome": c["nome"], "tipos": tk, "pontos": round(pontos, 3),
                      "respostas": sorted(c["venceu"], key=lambda v: -v["taxa"])[:3], "tampa": tampa,
                      "meta_taxa": round(m["winrate"], 3) if m else None, "meta_partidas": m["partidas"] if m else 0,
                      "resiste_a": [a["nome"] for a in ameacas if a["tipos"] and tk and melhor_ataque(a["tipos"], tk) <= 0.5],
                      "sofre_de": [a["nome"] for a in ameacas if a["tipos"] and tk and melhor_ataque(a["tipos"], tk) >= 2]})
    lista.sort(key=lambda x: -x["pontos"])
    sugestoes = lista[:limite]
    if orcamento:
        _anuncios(con, sugestoes, orcamento, moeda)

    return {"nick": perfil.get("jogador", {}).get("nick", nick), "faixa": faixa, "rank": rank,
            "totais": perfil.get("totais") or {}, "time": time_, "ameacas": ameacas, "buracos": buracos[:6],
            "tipos_castigam": tipos_castigam, "sugestoes": sugestoes, "meta": _resumo_meta(con, meta, faixa),
            "partidas_recentes": len(partidas),
            "vitorias_recentes": sum(1 for p in partidas if p.get("venci")),
            "temporada": perfil.get("partidasTemporada"), "orcamento": orcamento, "moeda": moeda,
            "velho": bool(perfil.get("_velho") or meta.get("_velho")), "nomes_tipo": NOMES_TIPO}


def _anuncios(con, sugestoes: list[dict], orcamento: float, moeda: str) -> None:
    """Os anúncios ativos de cada espécie sugerida que cabem no orçamento: o mais forte e o mais barato."""
    for s in sugestoes:
        rows = con.execute("""SELECT id, especie, nivel, shiny, nota, poder, potencia, preco, vendedor FROM pk_anuncios
                              WHERE ativo = 1 AND species_id = ? AND moeda = ? AND preco <= ?
                              ORDER BY poder DESC LIMIT 40""", (s["id"], moeda, orcamento)).fetchall()
        anuncios = [dict(r) for r in rows]
        s["anuncios"] = len(anuncios)
        s["mais_forte"] = anuncios[0] if anuncios else None
        s["mais_barato"] = min(anuncios, key=lambda r: r["preco"]) if anuncios else None
        if not anuncios:
            r = con.execute("SELECT MIN(preco), COUNT(*) FROM pk_anuncios WHERE ativo=1 AND species_id=? AND moeda=?",
                            (s["id"], moeda)).fetchone()
            s["mais_barato_fora"] = r[0]
            s["anuncios_fora"] = r[1]


def _resumo_meta(con, meta: dict, faixa: str) -> dict:
    linhas = meta.get("linhas") or []
    usados = linhas[:10]
    melhores = sorted([x for x in linhas if x.get("partidas", 0) >= 500], key=lambda x: -_nota_meta(x))[:10]
    times = []
    try:
        lad = tracker(con, "ladder", pagina=0, limite=50)
        for j in (lad.get("linhas") or [])[:TOP_JOGADORES]:
            try:
                p = tracker(con, "jogador", ttl_s=TTL_OUTRO_JOGADOR_S, nick=j["nick"])
            except ErroPvP:
                continue
            times.append({"posicao": j["posicao"], "nick": j["nick"], "pontos": j["pontos"], "taxa": j["winrate"],
                          "tier": j.get("tierId"),
                          "time": [{"id": x["id"], "nome": x["nome"]} for x in _time_atual(p.get("partidas") or [])]})
    except ErroPvP:
        pass
    # Espécies mais repetidas entre os times do topo.
    no_topo = Counter(x["nome"] for t in times for x in t["time"])
    enxuto = lambda x: {"id": x["id"], "nome": x["nome"], "tipos": x.get("tipos") or [], "partidas": x["partidas"],  # noqa: E731
                        "taxa": round(x["winrate"], 3), "dano": x.get("danoPorEntrada")}
    return {"faixa": faixa, "amostra": meta.get("amostra"), "temporada": meta.get("temporada"),
            "mais_usados": [enxuto(x) for x in usados], "melhor_taxa": [enxuto(x) for x in melhores],
            "times_topo": times, "repetidos_topo": no_topo.most_common(8)}


def pesos_especies(con, faixa: str = "alto", nick: str = "") -> dict[int, float]:
    """Nota de PvP por espécie (0 a 1) para o objetivo "PvP" da busca de Pokémon: a taxa do meta do rank
    e, com nick, o quanto a espécie responde às suas ameaças."""
    meta = tracker(con, "meta", ordem="uso", limite=200, faixa="" if faixa == "todas" else faixa)
    pesos = {int(x["id"]): _nota_meta(x) for x in meta.get("linhas") or []}
    if nick:
        try:
            a = analisar(con, nick, faixa, None, "gems", limite=60)
            for s in a["sugestoes"]:
                pesos[s["id"]] = max(pesos.get(s["id"], 0.5), 0.5 + max(s["pontos"], 0) / 2)
        except ErroPvP:
            pass
    if not pesos:
        return {}
    lo, hi = min(pesos.values()), max(pesos.values())
    return {k: (v - lo) / ((hi - lo) or 1) for k, v in pesos.items()}
