"""A força de um Pokémon no PvP ranqueado, pelas contas do próprio jogo (`shared/ginasios.mjs`).

O PvP e os ginásios usam a mesma régua: o "Poder no PvP" que a ficha do jogo mostra é o `poderNoGinasio`.
- **Nível de arena:** até o Nv 150 vale o nível real; acima, ele é achatado: `150 × (nível/150)^0,45`
  (`nivelNoGinasio`). Um Nv 300 luta como Nv 205 e um Nv 1000 como Nv 351. Por isso, no PvP, a evolução
  (as bases da espécie e os golpes de 600 da última forma) pesa muito mais que subir de nível.
- **Mínimo para o ranqueado:** Nv 150 (`PVP_NIVEL_MIN` de `shared/pvp-rank.mjs`).
- **⚔ no PvP:** `rating / 10⁷`, com `rating = dps × HP de combate × defesa média`. O dps é o do golpe que mais
  bate no nível de arena (`melhorGolpeDoGinasio`), contra uma defesa igual ao próprio ataque.
- **Duelo 1×1** (`compararDuelo1v1`, o comparador da calculadora do jogo): cada lado escolhe o golpe que mais
  bate no outro (tipo, STAB, ATK × DEF dele) e a força é `dps × HP de combate`; a variação de dano de 85% a
  100% decide quem ganha quando as forças estão perto. Não é a luta do tabuleiro (posição, alcance, cinco
  contra cinco): é a mesma aproximação que o jogo usa para comparar dois Pokémon.

Os stats seguem `statsNoNivel` do jogo, com o fator de cada stat que `evolucao._fatores` já calcula
(qualidade^exp × potência × shiny, ou o fator real dos stats de um anúncio).
"""
from __future__ import annotations

import random

from analise import evolucao, pvp

NIVEL_CHEIO = 150          # ARENA_NIVEL_CHEIO
EXPO_GINASIO = 0.45        # ARENA_EXPO_GINASIO
NIVEL_MIN_PVP = 150        # PVP_NIVEL_MIN
ESCALA_FORCA = 1e7         # GINASIO_ESCALA_FORCA
BASICO = (30, None, 1, 2000, 1)    # GOLPE_BASICO: poder 30, físico, 2 s
VARIACAO_DANO = (0.85, 1.0)
AMOSTRAS = 400


def nivel_arena(nivel: float) -> int:
    """`nivelNoGinasio`: o nível que conta no PvP."""
    n = max(1, int(nivel or 1))
    if n <= NIVEL_CHEIO:
        return n
    return max(NIVEL_CHEIO, evolucao._arred(NIVEL_CHEIO * (n / NIVEL_CHEIO) ** EXPO_GINASIO))


def lutador(esp: dict, nivel: int, ivs, fatores) -> dict:
    """Um Pokémon pronto para as contas de arena: tipos, stats no nível de arena e os golpes liberados."""
    na = nivel_arena(nivel)
    st = evolucao._stats(esp["b"], ivs, fatores, na)
    return {"nome": esp.get("n"), "tipos": list(esp.get("t") or [])[:2], "nivel": int(nivel),
            "nivel_arena": na, "stats": st, "golpes": [g for g in esp.get("g") or [] if g[4] <= na]}


def _base_dano(nivel, poder, atk, defesa) -> float:
    return ((2 * nivel) / 5 + 2) * poder * (atk / max(1, defesa)) / 50 + 2


def poder_pvp(x: dict) -> int:
    """`poderNoGinasio`: o ⚔ do PvP."""
    st, n = x["stats"], x["nivel_arena"]
    melhor, nota = BASICO, -1.0
    for g in x["golpes"]:
        atk, df = (st["atk"], st["def"]) if g[2] == 1 else (st["spAtk"], st["spDef"])
        v = _base_dano(n, g[0], atk, df) * (1.5 if g[1] in x["tipos"] else 1)
        if v > nota:
            melhor, nota = g, v
    atk = max(st["atk"], st["spAtk"])
    defesa = (st["def"] + st["spDef"]) / 2
    dps = ((2 * n) / 5 + 2) * melhor[0] * atk / 50 / (max(400, melhor[3]) / 1000)
    rating = dps * max(24, evolucao._arred(st["hp"] * 12)) * defesa
    return max(1, evolucao._arred(rating / ESCALA_FORCA))


def _forca_contra(a: dict, b: dict) -> tuple[float, dict]:
    """`metricasDeCombateContra`: o dps de A em B (o melhor golpe contra ele) × o HP de combate de A."""
    st, sb, n = a["stats"], b["stats"], a["nivel_arena"]
    melhor, nota = None, -1.0
    for g in a["golpes"]:
        ef = pvp.mult(g[1], b["tipos"])
        if ef == 0:
            continue
        atk = st["atk"] if g[2] == 1 else st["spAtk"]
        df = sb["def"] if g[2] == 1 else sb["spDef"]
        v = _base_dano(n, g[0], atk, df) * (1.5 if g[1] in a["tipos"] else 1) * ef
        if v > nota:
            melhor, nota = g, v
    if melhor is None:   # sem golpe que pegue: a Investida de um tipo que pegue
        tipo = next((t for t in (a["tipos"] or ["NORMAL"]) if pvp.mult(t, b["tipos"]) > 0), None)
        melhor = (30, tipo, 1, 2000, 1) if tipo else BASICO
    atk = st["atk"] if melhor[2] == 1 else st["spAtk"]
    df = sb["def"] if melhor[2] == 1 else sb["spDef"]
    ef = pvp.mult(melhor[1], b["tipos"]) if melhor[1] else 1.0
    dano = _base_dano(n, melhor[0], atk, df) * (1.5 if melhor[1] in a["tipos"] else 1) * max(0.0, ef)
    dps = dano / (max(400, melhor[3]) / 1000)
    return dps * max(24, evolucao._arred(st["hp"] * 12)), {"tipo": melhor[1], "poder": melhor[0], "ef": ef}


def duelo(a: dict, b: dict) -> dict:
    """`compararDuelo1v1` com a tabela de tipos: a chance de A ganhar de B (0 a 1)."""
    fa, ga = _forca_contra(a, b)
    fb, _ = _forca_contra(b, a)
    if abs(fa - fb) / max(fa, fb, 1) < 1e-6:
        p = 0.5
    else:
        rnd = random.Random(int(fa) * 997 + int(fb) * 991)
        lo, hi = VARIACAO_DANO
        vit = 0.0
        for _ in range(AMOSTRAS):
            ra, rb = fa * rnd.uniform(lo, hi), fb * rnd.uniform(lo, hi)
            vit += 1 if ra > rb else 0.5 if ra == rb else 0
        p = vit / AMOSTRAS
    return {"chance": round(p, 3), "razao": round(fa / max(fb, 1e-9), 3), "golpe": ga}


def rival(esp: dict, nivel: int, shiny: bool = False) -> dict:
    """Um Pokémon "típico" do outro lado: IV 16 em tudo, qualidade 1, P1 (sem saber o indivíduo dele)."""
    fat = evolucao._fatores((16,) * 6, 1.0, 1, shiny)
    return lutador(esp, nivel, (16,) * 6, fat)


# ---------------------------------------------------------------- vale evoluir para o PvP?

GANHO_MIN = 1.15           # evoluir "melhora" com pelo menos 15% a mais de ⚔ no PvP...
LIMIAR_DUELOS = 0.08       # ... ou 8 pontos a mais na chance média dos duelos contra as suas ameaças
MAX_PAGINAS_EXTRA = 15     # espécies fora dos 100 mais usados do meta: no máximo 15 páginas a mais no Tracker
NOTA_MIN_TIME = -0.03      # nota de PvP mínima para "entrar no time" (0 é neutro: 50% no meta, sem ameaças)
NOTA_FOLGA = 0.05          # "comprar pronto": anúncios com nota até 0,05 abaixo da projetada


def _mediana(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def _niveis_rivais(partidas: list[dict]) -> tuple[dict, int | None, dict]:
    """Das suas últimas partidas: o nível mediano de cada espécie do outro lado, o de todos e quem veio shiny."""
    por, todos, shiny = {}, [], {}
    for p in partidas:
        for pk in (p.get("ele") or {}).get("pks") or []:
            if pk.get("nivel"):
                por.setdefault(int(pk["id"]), []).append(int(pk["nivel"]))
                todos.append(int(pk["nivel"]))
                shiny.setdefault(int(pk["id"]), []).append(1 if pk.get("shiny") else 0)
    return ({k: _mediana(v) for k, v in por.items()}, _mediana(todos),
            {k: sum(v) * 2 > len(v) for k, v in shiny.items()})


def _contexto_meta(con, faixa: str, forcar: bool) -> dict:
    """Sem nick: só o meta da faixa (sem ameaças, a nota de PvP é só a taxa no meta)."""
    meta = pvp.tracker(con, "meta", forcar=forcar, ordem="uso", limite=200, faixa="" if faixa == "todas" else faixa)
    return {"perfil": {}, "partidas": [], "rank": {}, "faixa": faixa, "meta": meta,
            "meta_por_id": {int(x["id"]): x for x in meta.get("linhas") or []}, "time": [], "ameacas": [],
            "tipos": {}, "buracos": [], "cand": {}, "peso_total": 1}


def _prontos(con, especie_id: int, nota: float, nivel: int, shiny: bool, cb: float | None) -> dict | None:
    """O mesmo Pokémon já evoluído na loja: anúncios ativos da espécie final com nota parecida e pelo menos o
    nível com que o seu entraria no PvP (no mínimo 150)."""
    rows = con.execute("""SELECT moeda, MIN(preco), COUNT(*) FROM pk_anuncios
                          WHERE ativo = 1 AND species_id = ? AND shiny = ? AND nivel >= ? AND nota >= ?
                          GROUP BY moeda""", (especie_id, 1 if shiny else 0, nivel, nota - NOTA_FOLGA)).fetchall()
    if not rows:
        return None
    out = {"nota_min": round(nota - NOTA_FOLGA, 2), "nivel_min": nivel, "moedas": {}}
    for moeda, preco, n in rows:
        gemas = preco if moeda == "gems" else (preco / cb if cb else None)
        out["moedas"][moeda] = {"menor": preco, "anuncios": n, "em_gemas": round(gemas, 2) if gemas else None}
    gemas = [x["em_gemas"] for x in out["moedas"].values() if x["em_gemas"] is not None]
    out["menor_gemas"] = min(gemas) if gemas else None
    return out


def avaliar(con, r: dict, nick: str = "", faixa: str = "", forcar: bool = False, m=None) -> dict:
    """Vale evoluir este Pokémon para usar no PvP? `r` é o resultado de `evolucao.analisar`.

    Para a forma de agora e cada evolução final: o ⚔ do PvP (no Nv 150 se ainda não chegou lá, o mínimo do
    ranqueado), a nota de PvP da espécie para o seu time (a mesma das sugestões da aba PvP: responde às suas
    ameaças, taxa no meta do rank, encaixe de tipos) e os duelos 1×1 contra as suas ameaças, no nível em que
    elas aparecem nas suas partidas. Sem nick, vale só o meta da faixa (padrão: alto) e não há duelos."""
    from analise import caca, venda
    m = m or caca.motor()
    nick = (nick or "").strip()
    if nick:
        ctx = pvp._contexto(con, nick, faixa, forcar)
    else:
        ctx = _contexto_meta(con, faixa if faixa in pvp.FAIXAS else "alto", forcar)
    faixa = ctx["faixa"]
    fx = "" if faixa == "todas" else faixa
    extras = {"n": 0}

    def linha_meta(k):
        if k in ctx["meta_por_id"]:
            return ctx["meta_por_id"][k]
        if extras["n"] >= MAX_PAGINAS_EXTRA:
            return None
        extras["n"] += 1
        try:
            pag = pvp.tracker(con, "pokemon", id=k, faixa=fx)
        except pvp.ErroPvP:
            return None
        lin = pag.get("pokemon") or None
        if lin and lin.get("tipos"):
            ctx["tipos"].setdefault(k, lin["tipos"])
        return lin if lin and lin.get("partidas") else None

    def nota_especie(k, nome, tipos):
        lin = linha_meta(k)
        s = pvp._pontuar(ctx, k, nome, tipos, lin)
        s["meta_nota"] = round(pvp._nota_meta(lin), 3)
        s["meta_posicao"] = next((i + 1 for i, x in enumerate(ctx["meta"].get("linhas") or []) if int(x["id"]) == k), None)
        return s

    # Os rivais: as suas ameaças, no nível mediano em que aparecem nas suas partidas.
    niveis, nivel_rival, shiny_rival = _niveis_rivais(ctx["partidas"])
    rivais = []
    for a in ctx["ameacas"]:
        esp = m.esp.get(int(a["id"]))
        if not esp:
            continue
        nv = niveis.get(int(a["id"])) or nivel_rival or NIVEL_MIN_PVP
        x = rival(esp, nv, shiny_rival.get(int(a["id"]), False))
        rivais.append((a, x))
    peso_riv = sum(a["peso"] for a, _ in rivais) or 1

    ivs = tuple(int(r["ivs"][k]) for k in evolucao.STATS)
    fat = [float(r["fatores"][k]) for k in evolucao.STATS]

    def forma(pid, nivel):
        esp = m.esp[pid]
        nv = max(int(nivel), NIVEL_MIN_PVP)
        x = lutador(esp, nv, ivs, fat)
        s = nota_especie(pid, esp["n"], list(esp["t"]))
        duelos = []
        for a, rv in rivais:
            d = duelo(x, rv)
            duelos.append({"nome": a["nome"], "nivel": rv["nivel"], "nivel_arena": rv["nivel_arena"], "chance": d["chance"],
                           "golpe": d["golpe"]["tipo"], "efetivo": d["golpe"]["ef"]})
        media = round(sum(d["chance"] * a["peso"] for d, (a, _) in zip(duelos, rivais)) / peso_riv, 3) if duelos else None
        return {"id": pid, "nome": esp["n"], "tipos": list(esp["t"]), "nivel": int(nivel), "nivel_pvp": nv,
                "nivel_arena": x["nivel_arena"], "poder_pvp": poder_pvp(x), "nota": s, "duelos": duelos,
                "duelos_media": media, "no_time": any(pk["id"] == pid for pk in ctx["time"])}

    a = r["atual"]
    atual = forma(a["id"], a["nivel"])
    time_ = []
    for pk in ctx["time"]:
        s = nota_especie(pk["id"], pk["nome"], pk.get("tipos") or ctx["tipos"].get(pk["id"], []))
        time_.append({"id": pk["id"], "nome": pk["nome"], "nivel": pk.get("nivel"), "pontos": s["pontos"],
                      "meta_taxa": s["meta_taxa"], "taxa": pk.get("taxa")})
    linha = {a["id"]} | {e["id"] for f in r["finais"] for e in f["caminho"]}
    vagas = [t for t in time_ if t["id"] not in linha]   # quem ele tiraria do time (a própria linha não conta)
    pior = min(vagas, key=lambda t: t["pontos"]) if vagas and len(time_) >= 5 else None
    cb = venda.cambio(con)["coins_por_gema"]

    finais = []
    for f in r["finais"]:
        ev = forma(f["final"]["id"], f["caminho"][-1]["nivel"])
        ganho = ev["poder_pvp"] / max(1, atual["poder_pvp"])
        dd = (ev["duelos_media"] - atual["duelos_media"]) if rivais else None
        # A forma de agora quase nunca está no meta (ninguém joga de Charmander), então a comparação com ela é
        # pela força (⚔ do PvP e duelos); a espécie final é comparada com o seu time (ou com o meta, sem nick).
        melhora = ganho >= GANHO_MIN or (dd is not None and dd >= LIMIAR_DUELOS)
        piora = ganho < 1 and (dd is None or dd < 0)
        # Entra no time: já está nele, ou não atrapalha (nota ≥ −0,03: sem nick, taxa no meta de 48,6% ou mais) e
        # passa o mais fraco do time.
        entra = ev["no_time"] or (ev["nota"]["pontos"] >= NOTA_MIN_TIME and (pior is None or ev["nota"]["pontos"] >= pior["pontos"]))
        cod = "nao" if piora else ("vale" if entra else "melhora_fora") if melhora else "igual"
        horas = f.get("horas_ate_alvo") if f["caminho"][-1]["nivel"] < NIVEL_MIN_PVP and f.get("horas_ate_alvo") is not None else f.get("horas_ate_evoluir")
        finais.append(ev | {"veredito": cod, "entra": entra, "dif_duelos": None if dd is None else round(dd, 3),
                            "ganho_poder": round(ganho, 2),
                            "horas_ate_pvp": horas, "nota_final": f["nota"],
                            "prontos": _prontos(con, f["final"]["id"], f["nota"], ev["nivel_pvp"], bool(r.get("shiny")), cb)})
    ordem = sorted(range(len(finais)), key=lambda i: (-{"vale": 3, "melhora_fora": 2, "igual": 1, "nao": 0}[finais[i]["veredito"]],
                                                      -finais[i]["nota"]["pontos"]))
    perfil = ctx["perfil"]
    return {"nick": (perfil.get("jogador") or {}).get("nick") or nick or None, "faixa": faixa,
            "rank": ctx["rank"].get("rotulo"), "atual": atual, "finais": finais,
            "melhor": ordem[0] if finais else None, "time": time_, "pior_do_time": pior,
            "ameacas": [{"nome": a["nome"], "nivel": rv["nivel"], "nivel_arena": rv["nivel_arena"]} for a, rv in rivais],
            "nivel_rivais": nivel_rival, "nivel_arena_rivais": nivel_arena(nivel_rival) if nivel_rival else None,
            "nivel_min": NIVEL_MIN_PVP, "velho": bool(perfil.get("_velho") or ctx["meta"].get("_velho")),
            "lido_em": perfil.get("_ms") or ctx["meta"].get("_ms")}
