"""Ícone na bandeja do Windows que mantém o robô e o painel rodando em segundo plano.

Sem janelas na barra de tarefas: o robô e o painel rodam como processos ocultos, e este
ícone (perto do relógio) é o único sinal de que estão ligados. Clique esquerdo abre a
janelinha de status (src/mini.py); o direito tem o menu: painel, log, reiniciar, sair. Se um dos dois cair, ele é religado.

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

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
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


# ---------------------------------------------------------------- ícone

def desenhar_icone():
    """Pokébola em pixel art 16x16, ampliada sem suavizar."""
    from PIL import Image
    mapa = [
        ".....KKKKKK.....",
        "...KKRRRRRRKK...",
        "..KRRRRRRWWRRK..",
        ".KRRRRRRRRWWRRK.",
        ".KRRRRRRRRRRRRK.",
        "KRRRRRRRRRRRRRRK",
        "KRRRRRKKKKRRRRRK",
        "KKKKKKKWWKKKKKKK",
        "KKKKKKKWWKKKKKKK",
        "KWWWWWKKKKWWWWWK",
        "KWWWWWWWWWWWWWWK",
        ".KWWWWWWWWWWWWK.",
        ".KWWWWWWWWWWWWK.",
        "..KWWWWWWWWWWK..",
        "...KKWWWWWWKK...",
        ".....KKKKKK.....",
    ]
    cores = {"K": (26, 16, 24, 255), "R": (216, 64, 64, 255), "W": (240, 232, 220, 255), ".": (0, 0, 0, 0)}
    img = Image.new("RGBA", (16, 16))
    img.putdata([cores[c] for linha in mapa for c in linha])
    return img.resize((64, 64), Image.NEAREST)


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

    import pystray

    robo = Filho("Robô", "robo.py", None, "robo.erros.log",
                 "veja o motivo em data\\robo.log (se a sessão foi recusada, rode "
                 "python src\\robo.py --configurar).")
    painel = Filho("Painel", "painel.py", "painel.log", "painel.log",
                   "a porta 8770 já está em uso por outro programa.")
    filhos = (robo, painel)
    for f in filhos:
        f.ligar()

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

    menu = pystray.Menu(
        pystray.MenuItem("Status agora", abrir_mini, default=True),  # clique esquerdo no ícone
        pystray.MenuItem("Abrir painel", lambda *_: webbrowser.open(URL_PAINEL)),
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
    icon = pystray.Icon("pokeidle-tracker", desenhar_icone(), "PokeIdle Tracker", menu)
    parar = threading.Event()

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
