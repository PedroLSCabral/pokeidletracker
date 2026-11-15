"""Robô coletor: lê o mercado do jogo e grava no banco.

    python src/robo.py --configurar   # cola o nick + token da conta coletora (só no modo "conta")
    python src/robo.py                # roda para sempre
    python src/robo.py --uma-vez      # uma rodada só (teste)

Há dois jeitos de chegar ao jogo (`conexao` no config.local.json):
  - "extensao": a extensão do Idle Deck (pasta extensao/) liga a aba de uma conta ao robô por
    ws://127.0.0.1:8772 e o robô pede as leituras pelo socket que o jogo já tem aberto. Nenhuma
    conta fica presa ao robô.
  - "conta" (o antigo): o robô entra sozinho com uma conta só para coleta (nick + token).
Sem `conexao`, o robô usa a conta e também escuta a extensão; quando uma aba da extensão liga,
ele larga a conta, passa para "extensao" de vez e grava isso no config (para não voltar a entrar
com uma conta que agora pode estar aberta no Idle Deck). Sem token, ele só espera a extensão.

Ligado ao jogo, ele lê a vitrine de itens a cada minuto, pede o export quando o jogo libera
(1 por hora) e, a cada 3 h, lê a loja de Pokémon inteira. Se a conexão cair, entra de novo
(conta: espera 1 min, dobrando até 10 min; extensão: espera a aba voltar). O que ele está fazendo
agora fica em data/robo_agora.json (a janelinha de status, src/mini.py, lê esse arquivo).

Regras que o robô respeita:
  - 1 export por hora: usa o tempo que o próprio jogo devolve (`esperaMs`/`restaMs`).
  - Uma conexão por conta: se a conta coletora for aberta em outro lugar (código 4001),
    o robô espera e tenta de novo mais tarde, sem brigar pela sessão.
  - Recusas de conta (ban, sessão inválida...) param o robô com uma mensagem clara.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import notificar  # noqa: E402
from analise import caca, pvp, sinais  # noqa: E402
from coleta import coletor, importer, lojapk  # noqa: E402

MAX_ALERTAS_SEPARADOS = 5   # acima disso, o resto vai junto numa mensagem só

ROOT = caminhos.RAIZ
CONFIG = caminhos.CONFIG
LOG = caminhos.LOG_ROBO
AGORA = caminhos.AGORA_ROBO

URL_JOGO = os.environ.get("POKEIDLE_WS", "wss://pokeidle.io")
URL_ITENS = os.environ.get("POKEIDLE_ITENS", "https://pokeidle.io/assets/items.json")
ORIGEM = "https://pokeidle.io"
PORTA_EXTENSAO = int(os.environ.get("POKEIDLE_PORTA_EXTENSAO", "8772"))  # a mesma de extensao/fundo.js
VERSAO_EXTENSAO_MIN = (1, 0, 0)
USER_AGENT = "Mozilla/5.0 (pokeidletracker coletor)"

ESPERA_WELCOME_S = 90      # o login pode ficar na fila do gateway (ele manda `vivo` enquanto isso)
ESPERA_RESPOSTA_S = 30
CHECAR_NO_MAXIMO_A_CADA_S = 10 * 60
ESPERA_APOS_ERRO_S = 5 * 60
ESPERA_SESSAO_TOMADA_S = 30 * 60
ESPERA_EXT_OI_S = 10       # a aba da extensão se apresenta (`ext.oi`) logo que conecta
RECONEXAO_MIN_S, RECONEXAO_MAX_S = 60, 10 * 60   # queda de conexão: 1 min, dobrando até 10 min
SESSAO_ESTAVEL_S = 10 * 60                        # conectado por mais que isso zera a espera
PODAR_A_CADA_MS = 60 * 60_000
PVP_META_A_CADA_MS = 6 * 60 * 60_000   # pré-carga do meta do PvP (Tracker público, sem login)
CATALOGO_A_CADA_MS = 24 * 60 * 60_000  # catálogo de espécies e golpes do jogo (assets públicos), para o XP/h

RECUSAS_FATAIS = {
    "auth.contaBanida": "a conta coletora foi banida",
    "auth.ipBanido": "esta rede foi bloqueada pelo jogo",
    "auth.provedorBanido": "o provedor desta rede foi bloqueado pelo jogo",
    "auth.sessaoInvalida": "o token não vale mais; rode  python src/robo.py --configurar  de novo",
    "auth.precisaLogin": "o token não vale mais; rode  python src/robo.py --configurar  de novo",
    "auth.contaExcluida": "a conta coletora foi excluída",
    "login.precisaNick": "falta o nick no config.local.json",
}
RECUSAS_ESPERAR = {"login.limiteOnlineIp", "login.limiteOnlineIpLista"}  # rede cheia: tenta depois


_agora: dict = {}


def agora(**campos) -> None:
    """Publica o que o robô está fazendo neste momento em data/robo_agora.json (para a janelinha)."""
    _agora.update(campos)
    _agora.update(pid=os.getpid(), atualizado_ms=coletor.agora_ms())
    try:
        tmp = AGORA.with_suffix(".tmp")
        tmp.write_text(json.dumps(_agora, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, AGORA)
    except OSError:  # a janelinha pode estar lendo o arquivo nesse instante; vai na próxima
        pass


def _log_coletor(msg: str) -> None:
    log(msg)


class Fatal(Exception):
    pass


class SessaoTomada(Exception):
    pass


def log(msg: str) -> None:
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linha, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- configuração

def ler_config() -> dict:
    """O config, com `conexao` resolvida: "extensao", "conta" ou "auto" (conta + escuta a extensão)."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    modo = cfg.get("conexao")
    tem_conta = bool(cfg.get("nick") and cfg.get("token"))
    if modo not in ("extensao", "conta"):
        modo = "auto" if tem_conta else "extensao"
    if modo == "conta" and not tem_conta:
        raise Fatal(f"{CONFIG.name} sem nick ou token; rode  python src/robo.py --configurar"
                    " (ou use \"conexao\": \"extensao\")")
    cfg["_modo"] = modo
    if modo != "extensao" and not cfg.get("dispositivo"):
        cfg["dispositivo"] = str(uuid.uuid4())
        salvar_config(cfg)
    return cfg


def salvar_config(cfg: dict) -> None:
    tmp = CONFIG.with_suffix(".tmp")
    limpo = {k: v for k, v in cfg.items() if not k.startswith("_")}
    tmp.write_text(json.dumps(limpo, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG)


def configurar() -> None:
    print("Cole a linha copiada do console do navegador (o JSON com nick e token) e tecle Enter:")
    bruto = input().strip().strip("'\"") if sys.stdin.isatty() else sys.stdin.readline().strip()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        sys.exit("Isso não é um JSON válido. Copie de novo com o comando do passo a passo.")
    if not dados.get("nick") or not dados.get("token"):
        sys.exit("Faltou nick ou token no que foi colado.")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    cfg.update(nick=dados["nick"], token=dados["token"])
    cfg.setdefault("dispositivo", str(uuid.uuid4()))
    salvar_config(cfg)
    print(f"Pronto: {CONFIG.name} salvo para a conta {cfg['nick']}. "
          "Feche a aba do jogo dessa conta no navegador antes de ligar o robô.")


# ---------------------------------------------------------------- agenda

def proximos_horarios(con) -> dict[str, float]:
    """Quando (ms) cada tarefa fica liberada: export, vitrine, itens e loja de Pokémon."""
    return {
        "export": max(coletor.get(con, "export_liberado_em"), coletor.get(con, "export_trava_ate")),
        "vitrine": coletor.get(con, "vitrine_em") + coletor.VITRINE_A_CADA_MS,
        "itens": coletor.get(con, "itens_em") + coletor.ITENS_A_CADA_MS,
        # Varredura que falhou no meio só tenta de novo 30 min depois (não repete a leitura pesada).
        "pokemon": max(coletor.get(con, "pokemon_em") + lojapk.INTERVALO_MS,
                       coletor.get(con, "pokemon_tentativa_em") + 30 * 60_000),
    }


def proximas_tarefas(con) -> tuple[bool, bool, bool, bool, float]:
    """(exportar, vitrine, itens, loja de pokémon, segundos até a próxima tarefa)."""
    t = coletor.agora_ms()
    h = proximos_horarios(con)
    export_em, vitrine_em, itens_em, pokemon_em = h["export"], h["vitrine"], h["itens"], h["pokemon"]
    proxima = min(h.values())
    return t >= export_em, t >= vitrine_em, t >= itens_em, t >= pokemon_em, max(0, (proxima - t) / 1000)


def baixar_itens(con) -> None:
    req = urllib.request.Request(URL_ITENS, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        dados = json.loads(r.read())
    coletor.receber_itens(con, {"items": dados.get("items") or []})


# ---------------------------------------------------------------- uma rodada no socket

class Sessao:
    """Uma conexão com o jogo: um leitor em segundo plano separa as mensagens que interessam e
    `esperar()` devolve a primeira que satisfaz uma condição. Um ping a cada 25 s mantém a
    conexão viva nas sessões mais longas (a varredura da loja de Pokémon)."""

    INTERESSA = ('"welcome"', '"csv"', '"market"', '"erro"', '"sessao.renovada"', '"vivo"')

    def __init__(self, ws, cfg, extensao: bool = False):
        self.ws, self.cfg, self.extensao = ws, cfg, extensao
        self.fila: asyncio.Queue = asyncio.Queue()
        self.vivo_em = time.monotonic()

    async def _ler(self):
        try:
            async for bruto in self.ws:
                if not isinstance(bruto, str) or not any(k in bruto for k in self.INTERESSA):
                    continue
                m = json.loads(bruto)
                tipo = m.get("t")
                if tipo == "vivo":
                    self.vivo_em = time.monotonic()
                elif tipo == "sessao.renovada" and m.get("token") and not self.extensao:
                    self.cfg["token"] = m["token"]
                    salvar_config(self.cfg)
                    log("token renovado pelo jogo e salvo")
                elif tipo == "erro":
                    chave = m.get("chave") or ""
                    if self.extensao:  # a conta é do jogo do dono: um erro dela não para o robô
                        log(f"aviso do jogo (pela extensão): {chave or m.get('msg') or m}")
                    elif chave in RECUSAS_FATAIS:
                        await self.fila.put(Fatal(RECUSAS_FATAIS[chave]))
                    elif chave in RECUSAS_ESPERAR:
                        await self.fila.put(ConnectionError(f"rede cheia ({chave}); tentando mais tarde"))
                    else:
                        log(f"aviso do jogo: {chave or m.get('msg') or m}")
                else:
                    await self.fila.put(m)
        except websockets.ConnectionClosed as e:
            await self.fila.put(e)

    async def _pingar(self):
        while True:
            await asyncio.sleep(25)
            await self.ws.send('{"t":"ping"}')

    async def esperar(self, condicao, prazo_s: float):
        prazo = time.monotonic() + prazo_s
        while True:
            # Enquanto o gateway manda `vivo`, o login está andando na fila: o prazo estica.
            limite = max(prazo, self.vivo_em + 30)
            resta = limite - time.monotonic()
            if resta <= 0:
                raise TimeoutError("sem resposta do jogo")
            try:
                m = await asyncio.wait_for(self.fila.get(), timeout=min(resta, 5))
            except asyncio.TimeoutError:
                continue
            if isinstance(m, BaseException):
                raise m
            if condicao(m):
                return m

    async def dormir(self, segundos: float) -> None:
        """Dorme até a próxima tarefa, mas acorda na hora se a conexão cair (a fila recebe a queda)."""
        prazo = time.monotonic() + segundos
        while (resta := prazo - time.monotonic()) > 0:
            try:
                m = await asyncio.wait_for(self.fila.get(), timeout=resta)
            except asyncio.TimeoutError:
                return
            if isinstance(m, BaseException):
                raise m

    def _descartar_antigas(self):
        """Joga fora o que chegou sem ser pedido (numa sessão longa o jogo pode empurrar atualizações),
        para a resposta de agora não ser confundida com uma velha. Erros e quedas continuam valendo."""
        while not self.fila.empty():
            m = self.fila.get_nowait()
            if isinstance(m, BaseException):
                raise m

    async def pedir(self, msg: dict, condicao, prazo_s: float = ESPERA_RESPOSTA_S):
        self._descartar_antigas()
        await self.ws.send(json.dumps(msg))
        return await self.esperar(condicao, prazo_s)


async def pedir_export(s: Sessao, cfg: dict) -> None:
    agora(fase="export", detalhe="pedindo o export do mercado")
    m = await s.pedir({"t": "csv.pedir", "tipo": "mercado", "filtros": {}},
                      lambda m: m.get("t") == "csv" and m.get("tipo") == "mercado")
    con = importer.connect()
    try:
        if m.get("recusa"):
            rec = m["recusa"]
            coletor.receber_recusa(con, {"nick": cfg["nick"], "chave": rec.get("chave"),
                                         "restaMs": rec.get("restaMs")})
        elif m.get("ok") and isinstance((m.get("mercado") or {}).get("linhas"), list):
            mer = m["mercado"]
            coletor.receber_vendas(con, {"nick": cfg["nick"], "esperaMs": m.get("esperaMs"),
                                         "cortado": mer.get("cortado"), "linhas": mer["linhas"]})
        else:
            coletor.receber_falha(con, {"motivo": "resposta inesperada do export"})
    finally:
        con.close()


async def ler_vitrine(s: Sessao) -> None:
    agora(fase="vitrine", detalhe="lendo a vitrine de itens")
    m = await s.pedir({"t": "market.itens"}, lambda m: m.get("t") == "market" and m.get("aba") == "itens")
    con = importer.connect()
    try:
        coletor.receber_vitrine(con, {"resumo": m.get("resumo"), "medias": m.get("medias")})
    finally:
        con.close()


def tarefas_locais(con) -> None:
    """O que não precisa do jogo: nomes dos itens (1 vez por dia) e a poda da vitrine (1 vez por hora)."""
    _, _, itens, _, _ = proximas_tarefas(con)
    if itens:
        try:
            baixar_itens(con)
        except Exception as e:  # nomes de itens não são críticos
            log(f"items.json falhou: {e!r}")
            coletor.put(con, itens_em=coletor.agora_ms() - coletor.ITENS_A_CADA_MS + 3600_000)
    t = coletor.agora_ms()
    if t - coletor.get(con, "vitrine_poda_em") >= PODAR_A_CADA_MS:
        try:
            n = coletor.podar_vitrine(con)
            if n:
                log(f"vitrine: {n} linhas antigas resumidas (fica 1 retrato a cada 15 min depois de 3 dias)")
        except Exception as e:
            log(f"poda da vitrine falhou: {e!r}")
        coletor.put(con, vitrine_poda_em=t)
    if t - coletor.get(con, "pvp_meta_em") >= PVP_META_A_CADA_MS:
        coletor.put(con, pvp_meta_em=t)
        threading.Thread(target=_precarregar_pvp, name="pvp-meta", daemon=True).start()
    if t - coletor.get(con, "catalogo_jogo_em") >= CATALOGO_A_CADA_MS:
        coletor.put(con, catalogo_jogo_em=t)
        threading.Thread(target=_baixar_catalogo, name="catalogo-jogo", daemon=True).start()


def _baixar_ritmo() -> None:
    """O tempo por abate de cada hunt (da calculadora, 1 arquivo). Falhou, fica o de ontem ou a mediana."""
    try:
        log(f"caça: ritmo das hunts atualizado ({caca.baixar_ritmo()} hunts)")
    except Exception as e:
        log(f"caça: ritmo das hunts falhou (fica o anterior): {e!r}")


def _baixar_catalogo() -> None:
    """Em segundo plano: os arquivos públicos (~4 MB) com 1 s entre eles, uma vez por dia, e o ritmo das hunts."""
    _baixar_ritmo()
    try:
        log(f"caça: catálogo do jogo atualizado ({caca.baixar_catalogo()} espécies)")
    except Exception as e:
        log(f"caça: catálogo do jogo falhou: {e!r}")
        con = importer.connect()
        try:  # tenta de novo em 1 h
            coletor.put(con, catalogo_jogo_em=coletor.agora_ms() - CATALOGO_A_CADA_MS + 3600_000)
        finally:
            con.close()


def _precarregar_pvp() -> None:
    """Em segundo plano (são ~14 pedidos com 1,5 s entre eles): não segura a vitrine de minuto em minuto."""
    con = importer.connect()
    try:
        pvp.atualizar_meta(con)
        log("PvP: meta e times do topo atualizados (Tracker do jogo)")
    except Exception as e:
        log(f"PvP: pré-carga do meta falhou: {e!r}")
    finally:
        con.close()


async def sessao(cfg: dict, uma_vez: bool) -> None:
    """Modo conta: entra no jogo com a conta coletora e fica fazendo as tarefas."""
    async with websockets.connect(
        URL_JOGO, origin=ORIGEM, user_agent_header=USER_AGENT,
        max_size=64 * 2**20, open_timeout=30, ping_interval=None,
    ) as ws:
        s = Sessao(ws, cfg)
        leitor = asyncio.create_task(s._ler())
        pinger = asyncio.create_task(s._pingar())
        try:
            await ws.send(json.dumps({"t": "hello", "nick": cfg["nick"], "token": cfg["token"],
                                      "delta": 1, "dispositivo": cfg["dispositivo"]}))
            welcome = await s.esperar(lambda m: m.get("t") == "welcome", ESPERA_WELCOME_S)
            log("conectado (fica conectado entre as leituras)")
            await trabalhar(s, welcome, cfg, uma_vez)
        finally:
            pinger.cancel()
            leitor.cancel()


async def sessao_extensao(lig: "Ligacao", uma_vez: bool) -> None:
    """Modo extensão: usa o socket do jogo de uma aba do Idle Deck, pela extensão."""
    s = Sessao(lig.ws, {"nick": lig.nick}, extensao=True)
    leitor = asyncio.create_task(s._ler())
    try:
        # A aba manda o welcome (sem o estado da conta) logo depois do `ext.ok`. O jogo já pinga sozinho.
        await lig.ws.send(json.dumps({"t": "ext.ok"}, separators=(",", ":")))
        welcome = await s.esperar(lambda m: m.get("t") == "welcome", ESPERA_WELCOME_S)
        log(f"ligado pela extensão do Idle Deck (conta {lig.nick}, extensão v{lig.versao})")
        await trabalhar(s, welcome, {"nick": lig.nick}, uma_vez)
    finally:
        leitor.cancel()
        lig.terminar()


async def trabalhar(s: Sessao, welcome: dict, cfg: dict, uma_vez: bool) -> None:
    """Já ligado ao jogo: a cada volta faz o que estiver na hora e dorme até a próxima tarefa."""
    if not welcome.get("parcial"):
        try:  # as hunts e as constantes de caça vêm no welcome: guarda para o XP/h da busca
            r = caca.guardar_welcome(welcome)
            if not r["hunts"]:
                log(f"caça: o welcome não trouxe a lista de hunts ({r})")
        except Exception as e:
            log(f"caça: não deu para guardar o welcome: {e!r}")
    agora(erro=None, conectado_ms=coletor.agora_ms(), conexao="extensao" if s.extensao else "conta",
          conta=cfg.get("nick"))
    while True:
        con = importer.connect()
        try:
            tarefas_locais(con)
            exportar, vitrine, _, pokemon, _ = proximas_tarefas(con)
        finally:
            con.close()
        if exportar:
            await pedir_export(s, cfg)
        if vitrine:
            await ler_vitrine(s)
        if pokemon:
            await varrer_loja_pokemon(s)
        if exportar or vitrine or pokemon:
            agora(fase="alertas", detalhe="conferindo os alertas")
            checar_alertas()
        if uma_vez:
            return
        con = importer.connect()
        try:
            *_, espera = proximas_tarefas(con)
        finally:
            con.close()
        espera = min(max(espera, 1), CHECAR_NO_MAXIMO_A_CADA_S)
        agora(fase="esperando", detalhe="conectado, esperando a próxima tarefa", loja=None,
              acordar_ms=coletor.agora_ms() + espera * 1000)
        await s.dormir(espera)


# ---------------------------------------------------------------- extensão do Idle Deck

class Ligacao:
    """Uma aba do Idle Deck ligada pela extensão: o websocket dela, a conta e a versão."""

    def __init__(self, ws, nick: str, versao: str):
        self.ws, self.nick, self.versao = ws, nick, versao
        self.fim = asyncio.get_running_loop().create_future()

    def terminar(self) -> None:
        if not self.fim.done():
            self.fim.set_result(None)


def _origem_da_extensao(*args):
    """Só aceita conexões vindas de uma extensão (Origin chrome-extension://…). Uma página da internet
    não consegue forjar esse Origin, então nenhum site consegue se passar pela extensão."""
    if len(args) == 2 and hasattr(args[1], "headers"):   # websockets ≥ 13: (conexão, pedido)
        con, pedido = args
        origem = pedido.headers.get("Origin") or ""
        if not origem.startswith("chrome-extension://"):
            return con.respond(403, "só a extensão do PokeIdle Tracker\n")
        return None
    origem = args[1].get("Origin") or ""                 # websockets antigo: (caminho, cabeçalhos)
    if not origem.startswith("chrome-extension://"):
        return (403, [], b"so a extensao do PokeIdle Tracker\n")
    return None


class Extensao:
    """Servidor em 127.0.0.1 que recebe a extensão do Idle Deck. Uma aba por vez: as outras recebem
    4002 e tentam de novo mais tarde (a extensão pode estar em mais de uma conta)."""

    def __init__(self, porta: int = PORTA_EXTENSAO):
        self.porta = porta
        self.chegou: asyncio.Queue = asyncio.Queue()
        self.atual: Ligacao | None = None
        self.servidor = None

    async def iniciar(self) -> None:
        self.servidor = await websockets.serve(self._receber, "127.0.0.1", self.porta,
                                               process_request=_origem_da_extensao,
                                               max_size=64 * 2**20, ping_interval=20, ping_timeout=60)

    async def _receber(self, ws, *_):
        if self.atual is not None and not self.atual.fim.done():
            await ws.close(4002, "outra aba já está ligada")
            return
        try:
            oi = json.loads(await asyncio.wait_for(ws.recv(), ESPERA_EXT_OI_S))
        except Exception:
            return
        if not isinstance(oi, dict) or oi.get("t") != "ext.oi":
            await ws.close(4003, "esperava ext.oi")
            return
        versao = str(oi.get("versao") or "0")
        try:
            velha = tuple(int(x) for x in versao.split(".")) < VERSAO_EXTENSAO_MIN
        except ValueError:
            velha = True
        if velha:
            log(f"extensão v{versao} é antiga demais; recarregue a pasta extensao/ no Idle Deck")
            await ws.close(4004, "extensão antiga")
            return
        nick = str(oi.get("nick") or "?")[:40]
        self.atual = lig = Ligacao(ws, nick, versao)
        await self.chegou.put(lig)
        # A conexão fica aberta enquanto a sessão do robô usa a aba. Se a aba cair antes de o robô
        # pegá-la da fila, ela também termina (senão as outras abas ficariam recusadas à toa).
        fechou = asyncio.ensure_future(ws.wait_closed())
        try:
            await asyncio.wait({lig.fim, fechou}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            fechou.cancel()
            lig.terminar()

    async def proxima(self) -> Ligacao:
        """A próxima aba ligada que ainda está de pé."""
        while True:
            lig = await self.chegou.get()
            if not lig.fim.done() and lig.ws.state.name == "OPEN":
                return lig
            lig.terminar()


async def varrer_loja_pokemon(s: Sessao) -> None:
    """Lê a loja de Pokémon inteira (24 por página, com pausa entre páginas para não pesar no
    servidor) e guarda em `pk_anuncios` (ver lojapk.py).

    O servidor não passa da página 200, então a leitura vai moeda por moeda; numa moeda com mais
    anúncios que isso, uma segunda passada vem do mais caro para o mais barato até reencontrar o que
    já foi visto. Cada passada é gravada assim que termina."""
    t0 = coletor.agora_ms()
    con = importer.connect()
    try:
        coletor.put(con, pokemon_tentativa_em=t0)
        lojapk.preparar(con)   # num banco novo a tabela ainda não existe
        ultima = con.execute("SELECT anuncios FROM pk_varreduras ORDER BY snap_ms DESC LIMIT 1").fetchone()
    finally:
        con.close()
    estimado = ultima[0] if ultima else 0  # tamanho da última varredura, até o jogo dizer o total
    nome_moeda = {"orb": "gemas", "gold": "moedas"}
    vistos: set[int] = set()
    totais: dict[str, int] = {}
    paginas = 0
    for moeda, ordem in lojapk.PASSADAS:
        # Segunda passada (do mais caro) só se a primeira bateu no teto de páginas sem ver tudo.
        if ordem == "caros" and totais.get(moeda + ":vistos", 0) >= totais.get(moeda, 0):
            continue
        lote, novos_seguidos = [], 0
        for pagina in range(lojapk.ULTIMA_PAGINA + 1):
            filtro = {**lojapk.FILTRO_TUDO, "moeda": moeda, "ordem": ordem}
            m = None
            for tentativa in range(2):  # uma página sem resposta ganha mais uma chance
                try:
                    m = await s.pedir({"t": "market.listar", **filtro, "pagina": pagina, "especieId": 0},
                                      lambda m: m.get("t") == "market" and m.get("aba") == "vitrine", 20)
                    break
                except TimeoutError:
                    if tentativa:
                        raise
                    await asyncio.sleep(5)
            paginas += 1
            linhas = m.get("linhas") or []
            totais[moeda] = int(m.get("total") or 0)
            ids = {int(a["id"]) for a in linhas if a.get("id") is not None}
            ja_vistos = len(ids & vistos)
            vistos |= ids
            conhecido = sum(v for k, v in totais.items() if ":" not in k)
            agora(fase="loja", detalhe="lendo a loja de Pokémon", loja={
                "inicio_ms": t0, "passada": f"{nome_moeda.get(moeda, moeda)}, do mais {ordem[:-1]}",
                "pagina": pagina + 1, "paginas": paginas, "vistos": len(vistos),
                "total": max(conhecido, estimado)})
            lote.extend(linhas)
            if ordem == "caros":
                novos_seguidos = 0 if ja_vistos < len(ids) else novos_seguidos + 1
                if novos_seguidos >= 2:   # duas páginas seguidas só com repetidos: encontrou a outra passada
                    break
            fim = (not linhas or int(m.get("pagina") or 0) != pagina
                   or (pagina + 1) * int(m.get("porPagina") or 24) >= totais[moeda])
            if fim:
                break
            await asyncio.sleep(lojapk.PAUSA_ENTRE_PAGINAS_S)
        con = importer.connect()
        try:
            lojapk.gravar(con, lote, t0)
        finally:
            con.close()
        if ordem == "baratos":
            totais[moeda + ":vistos"] = len({int(a["id"]) for a in lote if a.get("id") is not None})
    total = sum(v for k, v in totais.items() if ":" not in k)
    completa = total > 0 and len(vistos) >= 0.97 * total
    con = importer.connect()
    try:
        lojapk.finalizar(con, t0, len(vistos), completa)
        coletor.put(con, pokemon_em=coletor.agora_ms())
    finally:
        con.close()
    log(f"loja de Pokémon: {len(vistos)} de {total} anúncios em {paginas} páginas"
        + ("" if completa else " — incompleta, anúncios antigos mantidos"))


def checar_alertas() -> None:
    """Fase 3: confere as regras de alerta com os dados recém-coletados e notifica."""
    con = importer.connect()
    try:
        novos = sinais.avaliar(con)
        if not novos:
            return
        novos.sort(key=lambda a: -a["valor"])
        separados, resto = novos[:MAX_ALERTAS_SEPARADOS], novos[MAX_ALERTAS_SEPARADOS:]
        for a in separados:
            ok, erros = notificar.enviar("PokeIdle Tracker", a["msg"])
            sinais.registrar(con, a, ok)
            log(f"ALERTA ({', '.join(ok) or 'só log'}): {a['msg']}" + (f"  falhas: {erros}" if erros else ""))
        if resto:
            texto = f"e mais {len(resto)} alerta(s): " + ", ".join(a["item"] for a in resto)
            ok, _ = notificar.enviar("PokeIdle Tracker", texto)
            for a in resto:
                sinais.registrar(con, a, ok)
            log(f"ALERTA: {texto}")
    except Exception as e:  # alerta nunca derruba a coleta
        log(f"alertas falharam: {e!r}")
    finally:
        con.close()


async def rodar(uma_vez: bool) -> None:
    cfg = ler_config()
    ext = Extensao()
    try:
        await ext.iniciar()
    except OSError as e:
        if cfg["_modo"] == "extensao":
            raise Fatal(f"a porta {ext.porta} da extensão está ocupada ({e.strerror or e})")
        log(f"não deu para escutar a extensão na porta {ext.porta} ({e!r}); segue só com a conta")
        ext = None
    if cfg["_modo"] == "extensao":
        log(f"robô ligado no modo extensão: esperando uma aba do Idle Deck em ws://127.0.0.1:{PORTA_EXTENSAO}")
    else:
        log(f"robô ligado com a conta {cfg['nick']} → {URL_JOGO}"
            + (f" (e escutando a extensão na porta {PORTA_EXTENSAO})" if ext else ""))
    try:
        await _rodar(cfg, ext, uma_vez)
    finally:
        if ext:
            ext.servidor.close()


async def _rodar(cfg: dict, ext: "Extensao | None", uma_vez: bool) -> None:
    reconexao = RECONEXAO_MIN_S
    while True:
        if cfg["_modo"] == "extensao":
            agora(fase="conectando", detalhe="esperando a aba do Idle Deck (extensão)", loja=None,
                  acordar_ms=None, conexao="extensao")
            lig = await ext.proxima()
            try:
                await sessao_extensao(lig, uma_vez)
                return  # só volta sem erro no --uma-vez
            except Fatal:
                raise
            except websockets.ConnectionClosed as e:
                codigo = e.rcvd.code if e.rcvd else None
                log(f"a aba do Idle Deck desligou (código {codigo}); esperando ela voltar")
                agora(erro="a aba do Idle Deck desligou")
            except Exception as e:
                log(f"sessão pela extensão falhou: {e!r}; esperando a aba de novo")
                agora(erro=f"a sessão pela extensão falhou: {e!r}"[:160])
            con = importer.connect()
            try:  # um export pedido e não respondido não fica travado, nem é pedido duas vezes seguidas
                coletor.put(con, export_trava_ate=coletor.agora_ms() + 2 * 60_000)
            finally:
                con.close()
            if uma_vez:
                return
            await asyncio.sleep(2)
            continue

        agora(fase="conectando", detalhe="entrando no jogo", loja=None, erro=None, acordar_ms=None,
              conexao="conta")
        inicio = time.monotonic()
        espera = 0
        trocou = False
        try:
            trocou = await _conta_ou_extensao(sessao(cfg, uma_vez), ext)
            if not trocou:
                return  # só volta sem erro no --uma-vez
        except Fatal:
            raise
        except websockets.ConnectionClosed as e:
            codigo = e.rcvd.code if e.rcvd else None
            if codigo == 4001:
                log("a conta coletora foi aberta em outro lugar (4001); esperando 30 min")
                espera = ESPERA_SESSAO_TOMADA_S
                agora(erro="a conta coletora foi aberta em outro lugar")
            else:
                if time.monotonic() - inicio > SESSAO_ESTAVEL_S:
                    reconexao = RECONEXAO_MIN_S
                espera, reconexao = reconexao, min(reconexao * 2, RECONEXAO_MAX_S)
                log(f"conexão fechada pelo jogo (código {codigo}); entrando de novo em {espera // 60} min" if espera >= 60
                    else f"conexão fechada pelo jogo (código {codigo}); entrando de novo em {espera} s")
                agora(erro=f"o jogo fechou a conexão (código {codigo})")
        except Exception as e:
            log(f"sessão falhou: {e!r}; tentando em 5 min")
            espera = ESPERA_APOS_ERRO_S
            agora(erro=f"a sessão falhou: {e!r}"[:160])
        if trocou:
            # A extensão chegou: daqui para a frente o robô não entra mais com a conta coletora.
            cfg["conexao"] = cfg["_modo"] = "extensao"
            salvar_config(cfg)
            log("extensão do Idle Deck ligada: o robô largou a conta coletora e passa a usar só a extensão "
                "(conexao = extensao no config)")
            continue
        con = importer.connect()
        try:  # um export pedido e não respondido não fica travado para sempre
            coletor.put(con, export_trava_ate=coletor.agora_ms() + espera * 1000)
        finally:
            con.close()
        if uma_vez:
            return
        agora(fase="esperando", detalhe="desconectado, esperando para entrar de novo", loja=None,
              acordar_ms=coletor.agora_ms() + espera * 1000)
        if await _esperar_ou_extensao(espera, ext):
            cfg["conexao"] = cfg["_modo"] = "extensao"
            salvar_config(cfg)
            log("extensão do Idle Deck ligada: o robô passa a usar só a extensão (conexao = extensao no config)")


async def _conta_ou_extensao(trabalho, ext: Extensao | None) -> bool:
    """Roda a sessão da conta; se uma aba da extensão ligar antes de ela acabar, cancela a sessão
    e devolve True (a aba fica na fila para o modo extensão pegar)."""
    tarefa = asyncio.ensure_future(trabalho)
    if ext is None:
        await tarefa
        return False
    olhar = asyncio.ensure_future(_espiar(ext))
    try:
        feito, _ = await asyncio.wait({tarefa, olhar}, return_when=asyncio.FIRST_COMPLETED)
        if tarefa in feito:
            tarefa.result()
            return False
        tarefa.cancel()
        try:
            await tarefa
        except (asyncio.CancelledError, Exception):
            pass
        return True
    finally:
        olhar.cancel()


async def _espiar(ext: Extensao) -> None:
    """Termina quando há uma aba da extensão na fila (sem tirá-la de lá)."""
    while ext.chegou.empty():
        await asyncio.sleep(0.5)


async def _esperar_ou_extensao(espera_s: float, ext: Extensao | None) -> bool:
    if ext is None:
        await asyncio.sleep(espera_s)
        return False
    try:
        await asyncio.wait_for(_espiar(ext), espera_s)
        return True
    except asyncio.TimeoutError:
        return False


# Código de saída de "parei de propósito, não adianta religar" (sessão recusada, robô duplicado).
# Diferente de 1, que é o que o Python devolve quando trava com um erro qualquer.
SAIDA_FATAL = 3
_mutex = None


def _unico_robo() -> bool:
    """No Windows, garante um robô só por PC (outro robô na mesma conta derrubaria este)."""
    global _mutex
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k32.CreateMutexW(None, False, "Local\\PokeIdleTrackerRobo")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    # As mensagens de export/vitrine (escritas pelo coletor) também vão para data/robo.log.
    coletor.log = _log_coletor
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configurar", action="store_true", help="salvar nick + token da conta coletora")
    ap.add_argument("--uma-vez", action="store_true", help="fazer uma rodada e sair")
    a = ap.parse_args()
    if a.configurar:
        return configurar()
    if not _unico_robo():
        # Só no console: o robô que está rodando continua escrevendo no data/robo.log normalmente.
        print("Já existe outro robô rodando neste PC (dois robôs na mesma conta se derrubam). "
              "Use o ícone da pokébola na bandeja para reiniciá-lo.", flush=True)
        sys.exit(SAIDA_FATAL)
    try:
        asyncio.run(rodar(a.uma_vez))
    except Fatal as e:
        log(f"PAROU: {e}")
        agora(fase="parado", detalhe=str(e), loja=None)
        sys.exit(SAIDA_FATAL)
    except KeyboardInterrupt:
        log("robô desligado")


if __name__ == "__main__":
    main()
