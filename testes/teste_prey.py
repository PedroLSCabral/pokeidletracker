"""Testes da recomendação do Prey (src/analise/prey.py) e do Prey no motor de caça (src/analise/caca.py).

Usa os dados do jogo em data/jogo/ (catálogo e hunts); sem eles, não roda. Não toca no banco nem no jogo.
    python testes/teste_prey.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from analise import caca, prey  # noqa: E402


def main() -> None:
    try:
        m = caca.motor()
    except caca.SemDados as e:
        print(f"pulado: {e}")
        return
    pid = next(k for k, v in m.esp.items() if v["n"] == "Abomasnow")
    e = m.esp[pid]
    L = 1176
    stats = {k: round((b + 32) * L / 100 * 1.3) for k, b in zip(("hp", "atk", "def", "spAtk", "spDef", "speed"), e["b"])}
    pk = {"speciesId": pid, "level": L, "stats": stats, "ivs": {"speed": 20}, "tipos": e["t"]}
    args = m.preparar(pid, L, stats, {"speed": 20}, e["t"])

    # 1) sem Prey, xp_na_hunt é igual ao que xp_h acha na melhor hunt
    melhor = m.xp_h(pid, L, stats, {"speed": 20}, e["t"], 1300)
    h = m.por_slug[melhor["slug"]]
    assert abs(m.xp_na_hunt(args, h)["xp_h"] - melhor["xp_h"]) < 1e-6
    alvo = h["mobs"][0]["pid"]

    # 2) cada bônus no motor
    base = m.xp_na_hunt(args, h)["xp_h"]
    spawn = [m.xp_na_hunt(args, h, {alvo: prey.efeito("spawn", est)})["xp_h"] for est in range(1, 6)]
    assert all(a < b for a, b in zip([base] + spawn, spawn)), "Spawn sobe com as estrelas"
    dano = m.xp_na_hunt(args, h, {alvo: prey.efeito("dano", 5)})["xp_h"]
    assert dano > base, "Dano encurta a luta de quem não mata de um golpe"
    assert m.xp_na_hunt(args, h, {alvo: prey.efeito("captura", 5)})["xp_h"] == base, "Capture Boost não muda XP"
    assert m.xp_na_hunt(args, h, {alvo + 99999: prey.efeito("spawn", 5)})["xp_h"] == base, "Prey de outra espécie não vale"
    # quem mata de um golpe: Dano não muda nada; Spawn sobe bem mais que para quem luta
    fraca = min((x for x in m.hunts if x["nivel"] <= 100), key=lambda x: x["nivel"])
    um = m.xp_na_hunt(args, fraca)
    pf = fraca["mobs"][0]["pid"]
    assert um["luta_s"] == 0
    assert m.xp_na_hunt(args, fraca, {pf: prey.efeito("dano", 5)})["xp_h"] == um["xp_h"]
    g1 = m.xp_na_hunt(args, fraca, {pf: prey.efeito("spawn", 5)})["xp_h"] / um["xp_h"] - 1
    g2 = spawn[-1] / base - 1
    assert g1 > g2 > 0, (g1, g2)
    assert 0.2 < g1 < 0.4, g1

    # 3) a recomendação: a espécie da melhor hunt com Spawn vence, e a outra cartela usa ela como referência
    lista = [alvo, pf] + [x for x in list(m.hunts_da_especie)[:30] if x not in (alvo, pf)][:7]
    r = prey.recomendar({"pokemon": pk, "treinador": 1300, "huntSlug": h["slug"],
                         "cartelas": [{"lista": lista, "pk": None, "bonus": "spawn", "est": 3, "n": [0, 0, 0]}, None]}, m)
    c = r["cartelas"][0]
    assert c["recomendado"] == alvo and c["vale"], c
    xs = [o.get("xp_h") or 0 for o in c["opcoes"]]
    assert xs == sorted(xs, reverse=True)
    assert r["cartelas"][1] == {"cartela": 1, "vazia": True}
    assert r["atual"]["slug"] == h["slug"] and r["atual"]["xp_h"] == round(base)

    r2 = prey.recomendar({"pokemon": pk, "treinador": 1300, "huntSlug": h["slug"], "cartelas": [
        {"lista": lista, "pk": alvo, "bonus": "spawn", "est": 3},
        {"lista": [pf], "pk": None, "bonus": "dano", "est": 5}]}, m)
    assert r2["cartelas"][1]["referencia"]["xp_h"] == round(spawn[2]), "a outra cartela já escolhida é a referência"
    assert r2["atual"]["xp_h"] == round(spawn[2]) and r2["atual"]["xp_h_sem"] == round(base)
    assert not r2["cartelas"][1]["vale"]

    # 4) captura e cartela sem bônus têm aviso; espécie bloqueada pelo nível do treinador fica sem XP
    r3 = prey.recomendar({"pokemon": pk, "treinador": 50, "cartelas": [{"lista": [alvo], "bonus": "captura", "est": 1}]}, m)
    assert "Capture Boost" in r3["cartelas"][0]["nota"]
    o = r3["cartelas"][0]["opcoes"][0]
    assert not o["liberada"] and not o.get("xp_h") and o["nivel_min"] == min(x["nivel"] for x in m.hunts_da_especie[alvo])
    r4 = prey.recomendar({"pokemon": pk, "treinador": 1300, "cartelas": [{"lista": [alvo]}]}, m)
    assert "roletada grátis" in r4["cartelas"][0]["nota"]
    for ruim in ({}, {"pokemon": {"speciesId": pid}}):
        try:
            prey.recomendar(ruim, m)
        except ValueError:
            pass
        else:
            raise AssertionError("corpo sem Pokémon tem que dar ValueError")
    print("prey: ok")


if __name__ == "__main__":
    main()
