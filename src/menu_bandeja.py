"""Menu do botão direito na pokébola da bandeja, desenhado no visual do jogo.

Faz o papel do menu cinza do Windows, como o menu da Steam: um quadro de madeira com o estado do
robô e do painel no topo e a lista de ações num vão escuro, com a linha sob o mouse em roxo.

Roda numa thread própria dentro da bandeja (um Tk escondido que só aparece quando pedem), e cada
ação escolhida roda noutra thread, para o menu nunca travar esperando um processo reiniciar.
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

import tema


@dataclass
class Item:
    texto: str
    acao: Callable[[], object] | None = None
    ativo: bool = True
    marcado: bool | None = None   # None: sem caixinha; True/False: mostra ✓ ou vazio
    destaque: bool = False        # a ação principal, em negrito


SEPARADOR = None


def _area_util(x: int, y: int) -> tuple[int, int, int, int]:
    """Retângulo útil (sem a barra de tarefas) do monitor onde está o ponto."""
    u32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    u32.MonitorFromPoint.restype = ctypes.c_void_p
    mon = u32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if mon and u32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(info)):
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    return 0, 0, u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)


class MenuBandeja:
    LARG_MIN = 250

    def __init__(self):
        self._fila: queue.Queue = queue.Queue()
        self._pronto = threading.Event()
        self._erro: Exception | None = None
        threading.Thread(target=self._rodar, name="menu-bandeja", daemon=True).start()
        self._pronto.wait(10)
        if self._erro:
            raise self._erro

    def mostrar(self, x: int, y: int, estado: list[tuple[str, str, str]], itens: list) -> None:
        """Abre o menu com o canto de baixo à direita no ponto (x, y), em pixels de tela.

        estado: linhas (rótulo, texto, cor da luz) mostradas no topo. itens: Item ou SEPARADOR.
        Pode ser chamado de qualquer thread.
        """
        self._fila.put((x, y, estado, itens))

    # ------------------------------------------------------------ thread do Tk
    def _rodar(self):
        try:
            import tkinter as tk
            self.tk = tk
            self.raiz = tk.Tk()
            self.raiz.withdraw()
            self.janela = None
            self._icone = self._pokebola()
        except Exception as e:  # noqa: BLE001 - a bandeja cai para o menu do Windows
            self._erro = e
            self._pronto.set()
            return
        self._pronto.set()
        self.raiz.after(50, self._olhar_fila)
        self.raiz.mainloop()

    def _pokebola(self):
        try:
            from PIL import ImageTk
            return ImageTk.PhotoImage(tema.desenhar_pokebola(64).resize((22, 22), 0))
        except Exception:  # noqa: BLE001 - o ícone é só enfeite
            return self.tk.PhotoImage(width=1, height=1)

    def _olhar_fila(self):
        try:
            while True:
                self._abrir(*self._fila.get_nowait())
        except queue.Empty:
            pass
        self.raiz.after(60, self._olhar_fila)

    def _fechar(self, *_):
        if self.janela is not None:
            self.janela.destroy()
            self.janela = None

    def _abrir(self, x, y, estado, itens):
        tk = self.tk
        self._fechar()
        j = self.janela = tk.Toplevel(self.raiz)
        j.withdraw()
        j.overrideredirect(True)
        j.attributes("-topmost", True)
        j.configure(bg=tema.MAD_LINHA)

        corpo = tema.moldura(tk, j)
        cab = tk.Frame(corpo, bg=tema.MAD)
        cab.pack(fill="x", pady=(0, 6))
        tk.Label(cab, image=self._icone, bg=tema.MAD).pack(side="left", padx=(0, 6))
        tema.titulo_contornado(tk, cab, "POKEIDLE TRACKER", 10).pack(side="left")

        # estado do robô e do painel
        if estado:
            st = tema.vao(tk, corpo, padx=10, pady=6)
            st.master.pack_configure(pady=(0, 6))  # o filete do vão é o pai do miolo
            for rotulo, texto, cor in estado:
                lin = tk.Frame(st, bg=tema.VAO)
                lin.pack(fill="x")
                luz = tk.Canvas(lin, width=10, height=10, bg=tema.VAO, highlightthickness=0)
                luz.create_rectangle(1, 1, 9, 9, outline=tema.MAD_LINHA, width=2, fill=cor)
                luz.pack(side="left", padx=(0, 7))
                tk.Label(lin, text=rotulo, font=(tema.TITULO, 8, "bold"), fg=tema.TINTA_3,
                         bg=tema.VAO).pack(side="left")
                tk.Label(lin, text=texto, font=(tema.TEXTO, 9), fg=tema.TINTA,
                         bg=tema.VAO).pack(side="left", padx=(6, 0))

        lista = tema.vao(tk, corpo, padx=3, pady=3)
        for it in itens:
            if it is SEPARADOR:
                tk.Frame(lista, bg=tema.VAO_LUZ, height=1).pack(fill="x", padx=8, pady=3)
                continue
            self._linha(lista, it)

        j.bind("<Escape>", self._fechar)
        j.bind("<FocusOut>", lambda e: self._fechar() if e.widget is j else None)

        # posição: canto de baixo à direita no mouse, sem sair da área útil do monitor
        j.update_idletasks()
        w, h = max(j.winfo_reqwidth(), self.LARG_MIN), j.winfo_reqheight()
        esq, topo, dir_, baixo = _area_util(x, y)
        px = max(esq, min(x - w, dir_ - w))
        py = max(topo, min(y - h, baixo - h))
        j.geometry(f"{w}x{h}+{px}+{py}")
        j.deiconify()
        j.lift()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(j.wm_frame(), 16))
        except Exception:  # noqa: BLE001
            pass
        j.focus_force()
        self.raiz.after(150, self._vigiar_clique_fora)

    def _vigiar_clique_fora(self):
        """Fecha se clicarem fora do menu (o FocusOut nem sempre chega numa janela sem moldura)."""
        j = self.janela
        if j is None:
            return
        u32 = ctypes.windll.user32
        if any(u32.GetAsyncKeyState(b) & 0x8000 for b in (0x01, 0x02, 0x04)):  # botões do mouse
            pt = wintypes.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            x0, y0 = j.winfo_rootx(), j.winfo_rooty()
            if not (x0 <= pt.x < x0 + j.winfo_width() and y0 <= pt.y < y0 + j.winfo_height()):
                self._fechar()
                return
        self.raiz.after(80, self._vigiar_clique_fora)

    def _linha(self, pai, it: Item):
        tk = self.tk
        cor_txt = tema.TINTA if it.ativo else tema.TINTA_3
        fonte = (tema.TITULO, 9, "bold") if it.destaque else (tema.TEXTO, 10)
        lin = tk.Frame(pai, bg=tema.VAO, cursor="hand2" if it.ativo else "")
        lin.pack(fill="x")
        marca = tk.Label(lin, text="✓" if it.marcado else "", width=2, font=(tema.TITULO, 9, "bold"),
                         fg=tema.SOBE, bg=tema.VAO)
        marca.pack(side="left", padx=(4, 0))
        txt = tk.Label(lin, text=it.texto, font=fonte, fg=cor_txt, bg=tema.VAO, anchor="w", pady=4)
        txt.pack(side="left", fill="x", expand=True, padx=(2, 14))
        if not it.ativo:
            return
        partes = (lin, marca, txt)

        def acender(on: bool):
            for p in partes:
                p.configure(bg=tema.RX if on else tema.VAO)
            txt.configure(fg="#ffffff" if on else cor_txt)
            marca.configure(fg="#ffffff" if on else tema.SOBE)

        def escolher(_e=None):
            self._fechar()
            if it.acao:
                threading.Thread(target=it.acao, name="acao-menu", daemon=True).start()

        for p in partes:
            p.bind("<Enter>", lambda _e: acender(True))
            p.bind("<Leave>", lambda e: acender(False) if not _dentro(lin, e) else None)
            p.bind("<ButtonRelease-1>", escolher)


def _dentro(w, e) -> bool:
    x, y = e.x_root - w.winfo_rootx(), e.y_root - w.winfo_rooty()
    return 0 <= x < w.winfo_width() and 0 <= y < w.winfo_height()
