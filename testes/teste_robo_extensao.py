"""Testa o robô no modo extensão contra uma aba FALSA (faz o papel da extensão do Idle Deck),
sem tocar no pokeidle.io nem no banco de verdade.

    python testes/teste_robo_extensao.py

Confere:
  1. uma conexão sem Origin de extensão é recusada (nenhum site se passa pela extensão);
  2. a aba se apresenta, o robô responde ext.ok, recebe o welcome e pede vitrine e export por ela;
  3. uma segunda aba recebe 4002 enquanto a primeira está ligada;
  4. quando a aba cai, o robô espera e aceita a próxima;
  5. no modo automático (com conta), uma aba da extensão faz o robô largar a conta e gravar
     "conexao": "extensao" no config.

Tudo acontece numa pasta temporária: banco, config, log e robo_agora.json.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pokeidle-teste-ext-"))
os.environ["POKEIDLE_WS"] = "ws://127.0.0.1:8797"
os.environ["POKEIDLE_PORTA_EXTENSAO"] = "8796"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import websockets  # noqa: E402

import robo  # noqa: E402
from coleta import coletor, importer, lojapk  # noqa: E402

URL_EXT = "ws://127.0.0.1:8796"
ORIGEM = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

db = TMP / "teste.db"
_conectar = importer.connect
importer.connect = lambda p=db: _conectar(p)
robo.CONFIG = TMP / "config.json"
robo.LOG = TMP / "robo.log"
robo.AGORA = TMP / "robo_agora.json"
robo.baixar_itens = lambda con: coletor.receber_itens(con, {"items": []})
robo.checar_alertas = lambda: None
robo.PVP_META_A_CADA_MS = 10**14
robo.CATALOGO_A_CADA_MS = 10**14
robo.caminhos.JOGO = TMP / "jogo"
robo.caminhos.WELCOME_JOGO = TMP / "jogo" / "welcome-dados.json"
lojapk.INTERVALO_MS = 10**14
coletor.VITRINE_A_CADA_MS = 1000

est = {"vitrines": 0, "exports": 0, "outros": [], "hellos": 0}


async def aba(nick="minhaconta", ficar_s=3.0):
    """Uma aba da extensão: apresenta-se, manda o welcome e responde aos pedidos por `ficar_s`."""
    ws = await websockets.connect(URL_EXT, origin=ORIGEM)
    await ws.send(json.dumps({"t": "ext.oi", "nick": nick, "versao": "1.0.0"}))
    ok = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert ok == {"t": "ext.ok"}, ok
    await ws.send(json.dumps({"t": "welcome", "hunts": []}))

    async def responder():
        async for raw in ws:
            m = json.loads(raw)
            if m["t"] == "market.itens":
                est["vitrines"] += 1
                await ws.send(json.dumps({"t": "market", "aba": "itens", "medias": {},
                                          "resumo": {"70080": {"anuncios": 1, "unidades": 1, "minOrb": 7}}}))
            elif m["t"] == "csv.pedir":
                est["exports"] += 1
                await ws.send(json.dumps({"t": "csv", "tipo": "mercado", "ok": True, "esperaMs": 3600000,
                                          "mercado": {"cortado": False, "linhas": []}}))
            else:
                est["outros"].append(m["t"])
    tarefa = asyncio.create_task(responder())
    await asyncio.sleep(ficar_s)
    return ws, tarefa


async def parar(tarefa):
    tarefa.cancel()
    try:
        await tarefa
    except (asyncio.CancelledError, Exception):
        pass


async def modo_extensao():
    robo.CONFIG.write_text(json.dumps({"conexao": "extensao"}))
    robo_t = asyncio.create_task(robo.rodar(uma_vez=False))
    await asyncio.sleep(0.5)

    try:
        await websockets.connect(URL_EXT)
        raise AssertionError("aceitou conexão sem Origin de extensão")
    except websockets.InvalidStatus if hasattr(websockets, "InvalidStatus") else websockets.InvalidStatusCode:
        print("1) conexão sem Origin de extensão: recusada")

    ws, t = await aba(ficar_s=3.5)
    print(f"2) pela aba: {est['vitrines']} vitrines, {est['exports']} export, outros pedidos {est['outros']}")
    assert est["vitrines"] >= 2 and est["exports"] == 1 and not est["outros"]

    outra = await websockets.connect(URL_EXT, origin=ORIGEM)
    try:
        await outra.send(json.dumps({"t": "ext.oi", "nick": "outra", "versao": "1.0.0"}))
        await asyncio.wait_for(outra.recv(), 5)
        raise AssertionError("a segunda aba foi aceita")
    except websockets.ConnectionClosed as e:
        print(f"3) segunda aba: fechada com {e.rcvd.code}")
        assert e.rcvd.code == 4002

    await ws.close()
    await parar(t)
    await asyncio.sleep(0.5)
    antes = est["vitrines"]
    ws, t = await aba(nick="outraconta", ficar_s=3)
    print(f"4) depois que a aba caiu, a próxima foi aceita: +{est['vitrines'] - antes} vitrines")
    assert est["vitrines"] > antes
    await ws.close()
    await parar(t)
    await parar(robo_t)
    await asyncio.sleep(0.5)


async def jogo(ws):
    try:
        json.loads(await ws.recv())
        est["hellos"] += 1
        await ws.send(json.dumps({"t": "welcome"}))
        async for raw in ws:
            m = json.loads(raw)
            if m["t"] == "market.itens":
                await ws.send(json.dumps({"t": "market", "aba": "itens", "medias": {}, "resumo": {}}))
    except websockets.ConnectionClosed:  # o robô largou a conta quando a aba ligou
        pass


async def modo_auto():
    robo.CONFIG.write_text(json.dumps({"nick": "coletora", "token": "tok1", "outra": 1}))
    async with websockets.serve(jogo, "127.0.0.1", 8797):
        robo_t = asyncio.create_task(robo.rodar(uma_vez=False))
        await asyncio.sleep(1.5)
        assert est["hellos"] == 1, est
        antes = est["vitrines"]
        ws, t = await aba(ficar_s=3)
        cfg = json.loads(robo.CONFIG.read_text())
        print(f"5) automático: a conta entrou {est['hellos']} vez, a aba ligou (+{est['vitrines'] - antes} vitrines)"
              f" e o config ficou com conexao={cfg.get('conexao')!r}")
        assert cfg.get("conexao") == "extensao" and cfg["token"] == "tok1" and cfg["outra"] == 1
        assert est["vitrines"] > antes and "_modo" not in cfg
        await ws.close()
        await parar(t)
        await asyncio.sleep(2)
        assert est["hellos"] == 1, "voltou a entrar com a conta depois que a aba caiu"
        await parar(robo_t)


async def main():
    await modo_extensao()
    await modo_auto()
    print("tudo certo")


asyncio.run(main())
