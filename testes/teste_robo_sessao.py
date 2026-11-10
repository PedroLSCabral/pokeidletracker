"""Testa o robô contra um jogo FALSO, sem tocar no pokeidle.io nem no banco de verdade.

    python testes/teste_robo_sessao.py

Confere:
  1. uma sessão só (um login) para várias leituras da vitrine, e um export;
  2. quando o jogo derruba a conexão, o robô entra de novo sozinho, sem abrir duas conexões;
  3. a vitrine gravada é a da resposta certa;
  4. a poda deixa 1 retrato a cada 15 min nos dados com mais de 3 dias.

Tudo acontece numa pasta temporária: banco, config, log e robo_agora.json.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pokeidle-teste-"))
os.environ["POKEIDLE_WS"] = "ws://127.0.0.1:8798"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import websockets  # noqa: E402

import robo  # noqa: E402
from coleta import coletor, importer, lojapk  # noqa: E402

db = TMP / "teste.db"
_conectar = importer.connect
importer.connect = lambda p=db: _conectar(p)
robo.CONFIG = TMP / "config.json"
robo.LOG = TMP / "robo.log"
robo.AGORA = TMP / "robo_agora.json"
robo.CONFIG.write_text(json.dumps({"nick": "coletora", "token": "tok1"}))
robo.baixar_itens = lambda con: coletor.receber_itens(con, {"items": [{"id": 2, "name": "Ancient Stone", "category": "stone"}]})
robo.checar_alertas = lambda: None
robo.PVP_META_A_CADA_MS = 10**14        # sem pré-carga do PvP (iria à internet)
lojapk.INTERVALO_MS = 10**14            # sem loja de Pokémon neste teste
coletor.VITRINE_A_CADA_MS = 1000        # 1 s no lugar de 1 min
robo.RECONEXAO_MIN_S = 1

est = {"hellos": 0, "vitrines": 0, "exports": 0, "derrubar_apos": None, "abertas": 0, "max_abertas": 0}


async def jogo(ws):
    est["abertas"] += 1
    est["max_abertas"] = max(est["max_abertas"], est["abertas"])
    try:
        json.loads(await ws.recv())
        est["hellos"] += 1
        await ws.send(json.dumps({"t": "welcome", "estado": {}}))
        vits = 0
        async for raw in ws:
            m = json.loads(raw)
            if m["t"] == "csv.pedir":
                est["exports"] += 1
                await ws.send(json.dumps({"t": "csv", "tipo": "mercado", "ok": True, "esperaMs": 3600000,
                                          "mercado": {"cortado": False, "linhas": []}}))
            elif m["t"] == "market.itens":
                est["vitrines"] += 1
                vits += 1
                await ws.send(json.dumps({"t": "market", "aba": "itens", "medias": {},
                                          "resumo": {"70080": {"anuncios": 1, "unidades": 1, "minOrb": est["vitrines"] * 10}}}))
                if est["derrubar_apos"] and vits >= est["derrubar_apos"]:
                    est["derrubar_apos"] = None
                    await ws.close(1012, "reiniciando")
                    return
    except websockets.ConnectionClosed:
        pass
    finally:
        est["abertas"] -= 1


async def main():
    async with websockets.serve(jogo, "127.0.0.1", 8798):
        tarefa = asyncio.create_task(robo.rodar(uma_vez=False))
        await asyncio.sleep(5.5)
        print(f"1) 5,5 s numa sessão: {est['hellos']} login, {est['vitrines']} vitrines, {est['exports']} export")
        assert est["hellos"] == 1 and est["vitrines"] >= 4 and est["exports"] == 1
        est["derrubar_apos"] = 1
        antes = est["hellos"]
        await asyncio.sleep(4)
        print(f"2) depois da queda: {est['hellos'] - antes} novo login, no máximo {est['max_abertas']} conexão por vez")
        assert est["hellos"] == antes + 1 and est["max_abertas"] == 1
        tarefa.cancel()
        try:
            await tarefa
        except asyncio.CancelledError:
            pass
    con = importer.connect()
    ult = con.execute("SELECT min_gems FROM vitrine ORDER BY snap_ms DESC LIMIT 1").fetchone()[0]
    print(f"3) último retrato gravado com o preço da última resposta: {ult} (esperado {est['vitrines'] * 10})")
    assert ult == est["vitrines"] * 10
    t = coletor.agora_ms()
    base = t - 5 * 24 * 3600_000
    with con:
        con.executemany("INSERT INTO vitrine (snap_ms, snap_ts, item_id, min_gems) VALUES (?,?,?,?)",
                        [(base + i * 60_000, "x", 70080, i) for i in range(60)])
    coletor.podar_vitrine(con)
    resto = con.execute("SELECT COUNT(*) FROM vitrine WHERE snap_ms < ?", (t - 3 * 24 * 3600_000,)).fetchone()[0]
    print(f"4) poda: 60 retratos de 1 h antiga viraram {resto}")
    assert resto in (4, 5)
    print("tudo certo")


asyncio.run(main())
