"""Ícone na bandeja do Windows que mantém o robô e o painel rodando em segundo plano.

Sem janelas na barra de tarefas: o robô e o painel rodam como processos ocultos, e este
ícone (perto do relógio) é o único sinal de que estão ligados. Como na Steam:
  - duplo clique abre o painel no navegador;
  - um clique abre a janelinha de status (src/mini.py);
  - o botão direito abre o menu no visual do jogo (src/menu_bandeja.py): estado, painel, log,
    reiniciar, ligar com o Windows e sair.
Se o robô ou o painel cair, ele é religado.

Uso:
    pythonw src\\bandeja.py            liga tudo (é o que o atalho de inicialização faz)
    pythonw src\\bandeja.py --abrir    liga tudo e abre o painel no navegador
    python  src\\bandeja.py --instalar cria o atalho para ligar junto com o Windows
    python  src\\bandeja.py --remover  apaga esse atalho
"""
from __future__ import annotations

import base64
import ctypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import caminhos  # noqa: E402
import tema  # noqa: E402

RAIZ = caminhos.RAIZ
DADOS = caminhos.DADOS
URL_PAINEL = "http://127.0.0.1:8770"
ATALHO = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/PokeIdle Tracker.lnk"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOG_MAX = 2_000_000  # bytes; acima disso o log antigo vira .old na próxima vez que o processo liga


def _python(janela: bool) -> str:
    exe = Path(sys.executable)
    alvo = exe.with_name("python.exe" if janela else "pythonw.exe")
    return str(alvo if alvo.exists() else exe)


def _abrir_log(nome: str):
    DADOS.mkdir(exist_ok=True)
    p = DADOS / nome
    try:
        if p.exists() and p.stat().st_size > LOG_MAX:
            p.replace(p.with_suffix(p.suffix + ".old"))
    except OSError:
        pass
    return open(p, "a", encoding="utf-8", buffering=1)


# ---------------------------------------------------------------- uma instância só

_mutex = None


def primeira_instancia() -> bool:
    global _mutex
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k32.CreateMutexW(None, False, "Local\\PokeIdleTrackerBandeja")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- atalho de inicialização

def _powershell(script: str) -> None:
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                   check=True, capture_output=True, creationflags=SEM_JANELA, timeout=30)


def instalar_atalho() -> None:
    def q(s) -> str:
        return "'" + str(s).replace("'", "''") + "'"
    _powershell(
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(ATALHO)});"
        f"$s.TargetPath = {q(_python(janela=False))};"
        f"$s.Arguments = {q(chr(34) + str(RAIZ / 'src' / 'bandeja.py') + chr(34))};"
        f"$s.WorkingDirectory = {q(RAIZ)};"
        f"$s.Description = 'Robô e painel do PokeIdle Tracker';"
        f"$s.Save()"
    )


def remover_atalho() -> None:
    ATALHO.unlink(missing_ok=True)


# ---------------------------------------------------------------- processos vigiados

class Filho:
    """Um processo oculto (robô ou painel) que é religado se cair."""

    def __init__(self, nome: str, script: str, log_saida: str | None, log_erro: str,
                 fatal: str):
        self.nome, self.script = nome, script
        self.log_saida, self.log_erro = log_saida, log_erro
        self.fatal = fatal  # o que dizer quando ele sai com código 3 (não adianta religar)
        self.proc: subprocess.Popen | None = None
        self.estado = "desligado"
        self.religar_em = 0.0
        self.quedas = 0

    def ligar(self) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        erro = _abrir_log(self.log_erro)
        saida = _abrir_log(self.log_saida) if self.log_saida else subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [_python(janela=True), str(RAIZ / "src" / self.script)],
            cwd=RAIZ, env=env, stdin=subprocess.DEVNULL, stdout=saida, stderr=erro,
            creationflags=SEM_JANELA,
        )
        self.estado = "rodando"
        self.ligado_em = time.time()

    def desligar(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.estado = "desligado"

    def reiniciar(self) -> None:
        self.desligar()
        self.quedas = 0
        self.ligar()

    def vigiar(self) -> str | None:
        """Chamado a cada poucos segundos. Devolve um aviso para mostrar, se houver."""
        if self.estado == "rodando" and self.proc and self.proc.poll() is not None:
            codigo = self.proc.returncode
            self.proc = None
            if codigo == 3:  # o próprio processo disse que não adianta religar
                self.estado = "parado"
                return f"{self.nome} parou: {self.fatal}"
            # Caiu por outro motivo: religa, esperando mais a cada queda seguida.
            if time.time() - self.ligado_em > 600:
                self.quedas = 0
            self.quedas += 1
            espera = min(30 * 2 ** (self.quedas - 1), 600)
            self.estado = "religando"
            self.religar_em = time.time() + espera
            return f"{self.nome} caiu (código {codigo}); religando em {espera} s."
        if self.estado == "religando" and time.time() >= self.religar_em:
            self.ligar()
        return None


def ultimo_registro_robo() -> str:
    try:
        with open(DADOS / "robo.log", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 2000))
            linhas = f.read().decode("utf-8", "replace").strip().splitlines()
        ult = linhas[-1]
        return ult[12:17] if ult.startswith("[") else "?"  # "[2026-11-08 16:31:42] ..." -> "16:31"
    except (OSError, IndexError):
        return "?"


# ---------------------------------------------------------------- ícone e cliques

WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205


def fase_robo() -> str:
    """O que o robô diz estar fazendo agora (data/robo_agora.json), em texto."""
    try:
        import json
        fase = json.loads(caminhos.AGORA_ROBO.read_text(encoding="utf-8")).get("fase") or ""
    except (OSError, ValueError):
        return ""
    return tema.FASES.get(fase, (fase, None))[0]


def classe_icone(pystray):
    """O ícone do pystray com os cliques da Steam: duplo clique, clique simples e menu próprio.

    O pystray só conhece clique simples (ação padrão) e o menu cinza do Windows. Aqui o clique
    simples espera o tempo de duplo clique do Windows antes de agir, para um duplo clique não
    abrir as duas coisas. Se o menu próprio falhar, cai para o menu do Windows.
    """
    class Icone(pystray.Icon):
        ao_duplo = ao_simples = ao_direito = None
        _timer = None
        _ignorar_solta = False

        def _cancelar(self):
            if self._timer:
                self._timer.cancel()
                self._timer = None

        def _on_notify(self, wparam, lparam):
            if lparam == WM_LBUTTONDBLCLK:
                self._cancelar()
                self._ignorar_solta = True  # o Windows manda mais um "soltou" depois do duplo clique
                threading.Thread(target=self.ao_duplo, daemon=True).start()
            elif lparam == WM_LBUTTONUP:
                if self._ignorar_solta:
                    self._ignorar_solta = False
                    return
                self._cancelar()
                espera = ctypes.windll.user32.GetDoubleClickTime() / 1000
                self._timer = threading.Timer(espera, self.ao_simples)
                self._timer.daemon = True
                self._timer.start()
            elif lparam == WM_RBUTTONUP and self.ao_direito:
                try:
                    self.ao_direito()
                except Exception as e:  # noqa: BLE001
                    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), f"menu próprio falhou: {e}", flush=True)
                    super()._on_notify(wparam, lparam)
            else:
                super()._on_notify(wparam, lparam)

    return Icone


def main() -> None:
    args = sys.argv[1:]
    if "--instalar" in args:
        instalar_atalho()
        print(f"Atalho criado: {ATALHO}")
        return
    if "--remover" in args:
        remover_atalho()
        print("Atalho removido.")
        return

    if not primeira_instancia():
        # Já está rodando: só abre o painel se pediram.
        if "--abrir" in args:
            webbrowser.open(URL_PAINEL)
        return

    # pythonw não tem console: erros da própria bandeja vão para um arquivo.
    sys.stdout = sys.stderr = _abrir_log("bandeja.log")
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # menu nítido em telas com escala
    except Exception:  # noqa: BLE001
        pass

    robo = Filho("Robô", "robo.py", None, "robo.erros.log",
                 "veja o motivo em data\\robo.log (se a sessão foi recusada, rode "
                 "python src\\robo.py --configurar).")
    painel = Filho("Painel", "painel.py", "painel.log", "painel.log",
                   "a porta 8770 já está em uso por outro programa.")
    filhos = (robo, painel)
    for f in filhos:
        f.ligar()

    try:
        import pystray
    except ImportError as e:
        # Sem a biblioteca do ícone, robô e painel rodam mesmo assim (vigiados, sem ícone) e um aviso explica.
        print(time.strftime("[%Y-%m-%d %H:%M:%S]"), f"sem ícone na bandeja: {e}", flush=True)
        threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(
            None, "O robô e o painel estão rodando, mas sem o ícone na bandeja: falta a biblioteca "
                  f"do ícone ({e.name}).\n\nPara corrigir, abra um terminal na pasta do projeto e rode:\n"
                  "pip install -r requirements.txt\n\nDepois reinicie o PC ou rode o iniciar.bat.",
            "PokeIdle Tracker", 0x40), daemon=True).start()
        while True:
            time.sleep(5)
            for f in filhos:
                aviso = f.vigiar()
                if aviso:
                    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), aviso, flush=True)

    def status_texto(_=None) -> str:
        return f"Robô: {robo.estado} (último registro {ultimo_registro_robo()})"

    def painel_texto(_=None) -> str:
        return f"Painel: {painel.estado}"

    def com_inicio(_=None) -> bool:
        return ATALHO.exists()

    def alternar_inicio(icon, _item):
        try:
            remover_atalho() if ATALHO.exists() else instalar_atalho()
        except Exception as e:  # noqa: BLE001 - mostrar qualquer falha para o usuário
            icon.notify(f"Não consegui mudar o atalho: {e}", "PokeIdle Tracker")
        icon.update_menu()

    def abrir_log(_icon, _item):
        os.startfile(DADOS / "robo.log")

    def abrir_pasta(_icon, _item):
        os.startfile(DADOS)

    def sair(icon, _item):
        parar.set()
        for f in filhos:
            f.desligar()
        icon.stop()

    def abrir_mini(*_):
        subprocess.Popen([_python(janela=False), str(RAIZ / "src" / "mini.py")], cwd=RAIZ,
                         creationflags=SEM_JANELA)

    def abrir_painel(*_):
        webbrowser.open(URL_PAINEL)

    # Menu cinza do Windows: só aparece se o menu no visual do jogo não puder abrir.
    menu = pystray.Menu(
        pystray.MenuItem("Abrir painel", abrir_painel, default=True),
        pystray.MenuItem("Status agora", abrir_mini),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(status_texto, None, enabled=False),
        pystray.MenuItem(painel_texto, None, enabled=False),
        pystray.MenuItem("Ver log do robô", abrir_log),
        pystray.MenuItem("Abrir pasta de dados", abrir_pasta),
        pystray.MenuItem("Reiniciar robô", lambda icon, _: (robo.reiniciar(), icon.update_menu())),
        pystray.MenuItem("Reiniciar painel", lambda icon, _: (painel.reiniciar(), icon.update_menu())),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Ligar junto com o Windows", alternar_inicio, checked=com_inicio),
        pystray.MenuItem("Sair (desliga robô e painel)", sair),
    )
    icon = classe_icone(pystray)("pokeidle-tracker", tema.desenhar_pokebola(), "PokeIdle Tracker", menu)
    parar = threading.Event()

    try:
        import menu_bandeja
        menu_jogo = menu_bandeja.MenuBandeja()
    except Exception as e:  # noqa: BLE001 - sem Tk, fica o menu do Windows
        print(time.strftime("[%Y-%m-%d %H:%M:%S]"), f"menu próprio indisponível: {e}", flush=True)
        menu_jogo = None

    def luz(estado: str) -> str:
        return tema.SOBE if estado == "rodando" else tema.OURO if estado == "religando" else tema.DESCE

    def abrir_menu_jogo():
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        fase = fase_robo() if robo.estado == "rodando" else ""
        estado = [
            ("ROBÔ", robo.estado + (f" · {fase}" if fase else ""), luz(robo.estado)),
            ("PAINEL", "no ar" if painel.estado == "rodando" else painel.estado, luz(painel.estado)),
            ("ÚLTIMO REGISTRO", ultimo_registro_robo(), tema.TINTA_3),
        ]
        I = menu_bandeja.Item
        itens = [
            I("Abrir painel", abrir_painel, destaque=True),
            I("Status agora", abrir_mini),
            menu_bandeja.SEPARADOR,
            I("Ver log do robô", lambda: abrir_log(None, None)),
            I("Abrir pasta de dados", lambda: abrir_pasta(None, None)),
            menu_bandeja.SEPARADOR,
            I("Reiniciar robô", lambda: (robo.reiniciar(), icon.update_menu())),
            I("Reiniciar painel", lambda: (painel.reiniciar(), icon.update_menu())),
            menu_bandeja.SEPARADOR,
            I("Ligar junto com o Windows", lambda: alternar_inicio(icon, None), marcado=com_inicio()),
            I("Sair (desliga robô e painel)", lambda: sair(icon, None)),
        ]
        menu_jogo.mostrar(pt.x, pt.y, estado, itens)

    icon.ao_duplo = abrir_painel
    icon.ao_simples = abrir_mini
    icon.ao_direito = abrir_menu_jogo if menu_jogo else None

    def vigia():
        while not parar.wait(5):
            for f in filhos:
                aviso = f.vigiar()
                if aviso:
                    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), aviso, flush=True)
                    try:
                        icon.notify(aviso, "PokeIdle Tracker")
                    except Exception:  # noqa: BLE001
                        pass
            ok = all(f.estado == "rodando" for f in filhos)
            icon.title = ("PokeIdle Tracker: tudo ligado" if ok else
                          f"PokeIdle Tracker: robô {robo.estado}, painel {painel.estado}")[:127]
            icon.update_menu()

    def ao_ligar(icon):
        icon.visible = True
        threading.Thread(target=vigia, daemon=True).start()
        if "--abrir" in args:
            time.sleep(1.5)
            webbrowser.open(URL_PAINEL)

    try:
        icon.run(setup=ao_ligar)
    finally:
        parar.set()
        for f in filhos:
            f.desligar()


if __name__ == "__main__":
    main()
