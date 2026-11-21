"""Prey: qual dos 9 Pokémon da cartela rende mais XP/h para o Pokémon que está upando.

O Prey do jogo (novidades v48/v49, regra em `shared/prey.mjs`, cliente 1.459) dá, até a virada das 18:00 de
Brasília, um bônus **contra uma espécie selvagem** escolhida entre 9, e só nas hunts do Mapa. A roletada grátis
revela os 9, o bônus e as estrelas de uma vez; depois o jogador escolhe um. Então, na hora da escolha, o bônus e
o valor já são sabidos e a pergunta é só: em qual das 9 espécies (caçando numa hunt onde ela nasce) o Pokémon
faz mais XP/h com esse bônus?

Os bônus (`PREY_VALOR`, por estrela):
- **Spawn** +1 a +5 criaturas dela por onda, dentro dos bandos que já existem (`repartirExtras`): mais abates
  por onda sem mais caminhada;
- **Dano** +10% a +50% do nosso dano nela (`multDanoPrey`/`danoPve`): encurta a luta; para quem já mata de um
  golpe não muda nada;
- **Defensivo** −10% a −50% do dano dela na gente: só conta quando ela mata o Pokémon de um golpe;
- **Capture Boost** +2% a +10% na chance de captura: não muda o XP.

A conta de cada hunt é a do motor de caça (`analise/caca.py`, `Motor.xp_na_hunt` com `prey`). Cada hunt do jogo
tem uma espécie só, então a espécie da cartela leva às hunts dela (`Motor.hunts_da_especie`), as liberadas
para o nível do treinador. O ganho é contra a melhor hunt do Pokémon sem o Prey (ou com o Pokémon já escolhido
na outra cartela: só se caça uma hunt por vez).
"""
from __future__ import annotations

from analise import caca

PREY_VALOR = {
    "dano": (10, 20, 30, 40, 50),
    "defesa": (10, 20, 30, 40, 50),
    "captura": (2, 4, 6, 8, 10),
    "spawn": (1, 2, 3, 4, 5),
}
NOMES = {"dano": "Dano", "defesa": "Defensivo", "captura": "Capture Boost", "spawn": "Spawn"}
MAX_EXTRAS = 5          # PREY_MAX_EXTRAS: o Spawn não passa de +5 por onda
OPCOES = 9


def valor(bonus: str, est: int) -> int:
    v = PREY_VALOR.get(bonus)
    if not v:
        return 0
    return v[min(5, max(1, int(est or 1))) - 1]


def efeito(bonus: str, est: int) -> dict:
    """O bônus de uma cartela no formato do motor (`Motor._hunt`, parâmetro `prey`)."""
    v = valor(bonus, est)
    if bonus == "dano":
        return {"dano": 1 + v / 100}
    if bonus == "defesa":
        return {"defesa": 1 - v / 100}
    if bonus == "spawn":
        return {"extras": min(MAX_EXTRAS, v)}
    return {}


def texto(bonus: str, est: int) -> str:
    v = valor(bonus, est)
    sinal = f"−{v}%" if bonus == "defesa" else f"+{v}" if bonus == "spawn" else f"+{v}%"
    return f"{NOMES.get(bonus, bonus)} {sinal} · {'★' * min(5, max(1, int(est or 1)))}"


def _cartela(bruta) -> dict | None:
    """Uma cartela do `estado.eu.automation.prey` (lista, pk, bonus, est), validada; None se vazia."""
    if not isinstance(bruta, dict):
        return None
    lista = []
    for x in bruta.get("lista") or []:
        try:
            pid = int(x)
        except (TypeError, ValueError):
            continue
        if pid > 0 and pid not in lista:
            lista.append(pid)
    if not lista:
        return None
    pk = bruta.get("pk")
    try:
        pk = int(pk) if pk is not None else None
    except (TypeError, ValueError):
        pk = None
    bonus = bruta.get("bonus") if bruta.get("bonus") in PREY_VALOR else None
    try:
        est = min(5, max(1, int(bruta.get("est") or 0))) if bonus else None
    except (TypeError, ValueError):
        est = None
    return {"lista": lista[:OPCOES], "pk": pk if pk in lista else None, "bonus": bonus, "est": est}


def _resumo(r: dict | None) -> dict | None:
    if not r:
        return None
    return {"hunt": r["hunt"], "slug": r["slug"], "nivel_hunt": r["nivel_hunt"], "xp_h": round(r["xp_h"]),
            "kph": round(r["kph"]), "morre": r["morre"]}


def recomendar(corpo: dict, m: caca.Motor | None = None) -> dict:
    """A recomendação para as cartelas de hoje.

    `corpo`: `pokemon` (speciesId, level, stats, ivs, tipos, nome, como no `estado` do jogo), `treinador` (nível),
    `huntSlug` (a hunt de agora, opcional) e `cartelas` (as de `automation.prey.cartelas`, null para as vazias).
    """
    m = m or caca.motor()
    pk = corpo.get("pokemon") or {}
    try:
        especie, nivel = int(pk.get("speciesId") or 0), int(pk.get("level") or 0)
        treinador = int(corpo.get("treinador") or 0) or None
    except (TypeError, ValueError):
        raise ValueError("Pokémon ou nível inválido")
    stats = pk.get("stats") if isinstance(pk.get("stats"), dict) else None
    ivs = pk.get("ivs") if isinstance(pk.get("ivs"), dict) else None
    tipos = [t for t in (pk.get("tipos") or []) if isinstance(t, str)][:2] or None
    if not especie or not nivel or not stats:
        raise ValueError("faltam a espécie, o nível ou os stats do Pokémon")
    args = m.preparar(especie, nivel, stats, ivs, tipos)
    if args is None:
        raise ValueError(f"espécie {especie} fora do catálogo do jogo (o robô baixa o catálogo 1 vez por dia)")
    liberada = lambda h: not treinador or h["nivel"] <= treinador  # noqa: E731

    melhor = m.xp_h(especie, nivel, stats, ivs, tipos, treinador)
    h_atual = m.por_slug.get(corpo.get("huntSlug") or "")
    cartelas = [_cartela(c) for c in (corpo.get("cartelas") or [])[:2]]

    # O Prey já escolhido em cada cartela (pk + bônus): vale junto nas contas (duas cartelas nunca têm a mesma
    # espécie, então os efeitos não se somam no mesmo alvo).
    escolhidos = {i: c for i, c in enumerate(cartelas) if c and c["pk"] and c["bonus"]}

    def prey_de(i_fora=None, extra=None):
        p = {c["pk"]: efeito(c["bonus"], c["est"]) for i, c in escolhidos.items() if i != i_fora}
        if extra:
            p.update(extra)
        return p

    cache: dict = {}

    def na_hunt(h, prey):
        chave = (h["slug"], tuple(sorted((k, tuple(sorted(v.items()))) for k, v in prey.items())))
        if chave not in cache:
            cache[chave] = m.xp_na_hunt(args, h, prey or None)
        return cache[chave]

    def melhor_com_escolhidos(i_fora=None):
        """A melhor hunt sem Prey ou numa hunt de um Pokémon escolhido nas outras cartelas."""
        r = melhor
        for i, c in escolhidos.items():
            if i == i_fora:
                continue
            for h in m.hunts_da_especie.get(c["pk"], []):
                if liberada(h):
                    x = na_hunt(h, prey_de(i_fora))
                    if x and (r is None or x["xp_h"] > r["xp_h"]):
                        r = x
        return r

    saida = []
    for i, c in enumerate(cartelas):
        if not c:
            saida.append({"cartela": i, "vazia": True})
            continue
        ref = melhor_com_escolhidos(i)
        ref_xp = ref["xp_h"] if ref else 0
        opcoes = []
        for pid in c["lista"]:
            hs = m.hunts_da_especie.get(pid, [])
            abertas = [h for h in hs if liberada(h)]
            op = {"pk": pid, "nome": (m.esp.get(pid) or {}).get("n") or f"#{pid}",
                  "nivel_min": min((h["nivel"] for h in hs), default=None), "liberada": bool(abertas)}
            if c["bonus"]:
                ef = efeito(c["bonus"], c["est"])
                bom = sem = None
                for h in abertas:
                    x = na_hunt(h, prey_de(i, {pid: ef}))
                    if x and (bom is None or x["xp_h"] > bom["xp_h"]):
                        bom = x
                        sem = na_hunt(h, prey_de(i))
                if bom:
                    op.update(_resumo(bom))
                    op["xp_h_sem"] = round(sem["xp_h"]) if sem else None
                    op["ganho_bonus"] = (bom["xp_h"] / sem["xp_h"] - 1) if sem and sem["xp_h"] else None
                    # a busca rápida do motor pode não ter visto esta hunt: a referência nunca fica abaixo dela sem o bônus
                    base = max(ref_xp, sem["xp_h"] if sem else 0)
                    op["ganho"] = (bom["xp_h"] / base - 1) if base else None
                    if h_atual and h_atual["slug"] == bom["slug"]:
                        op["atual"] = True
            opcoes.append(op)
        opcoes.sort(key=lambda o: (-(o.get("xp_h") or -1), o["nivel_min"] or 1e12))
        rec = opcoes[0] if opcoes and opcoes[0].get("xp_h") else None
        nota = None
        if not c["bonus"]:
            nota = "Faça a roletada grátis para ver o bônus e as estrelas."
        elif c["bonus"] == "captura":
            nota = "Capture Boost não muda o XP: escolha pela espécie que você quer capturar."
        elif not rec:
            nota = "Nenhuma das 9 tem hunt liberada para o seu nível de treinador em que o Pokémon mate."
        elif (rec.get("ganho") or 0) <= 0.001:
            nota = (f"Nenhuma das 9 passa a melhor hunt dele hoje ({ref['hunt']}, Nv {ref['nivel_hunt']}), "
                    "nem com o bônus: a primeira é a que menos perde."
                    if ref else "Nenhuma das 9 rende XP com esse bônus.")
        saida.append({"cartela": i, "bonus": c["bonus"], "est": c["est"], "valor": valor(c["bonus"], c["est"]) if c["bonus"] else None,
                      "texto": texto(c["bonus"], c["est"]) if c["bonus"] else None, "escolhido": c["pk"],
                      "referencia": _resumo(ref), "recomendado": rec["pk"] if rec else None,
                      "vale": bool(rec and (rec.get("ganho") or 0) > 0.001),
                      "opcoes": opcoes, "nota": nota})

    atual = None
    if h_atual:
        sem = na_hunt(h_atual, {})
        com = na_hunt(h_atual, prey_de()) if escolhidos else sem
        atual = {**(_resumo(com) or {"hunt": h_atual["nome"], "slug": h_atual["slug"], "nivel_hunt": h_atual["nivel"]}),
                 "xp_h_sem": round(sem["xp_h"]) if sem else None}
    return {"pokemon": {"speciesId": especie, "nivel": nivel, "nome": pk.get("nome") or (m.esp.get(especie) or {}).get("n")},
            "treinador": treinador, "melhor": _resumo(melhor), "atual": atual, "cartelas": saida}
