"""Janelinha de status: o que o robô está fazendo agora e quando vem a próxima tarefa.

Abre pelo ícone da pokébola na bandeja (clique esquerdo). Fecha no X ou com Esc. Não aparece
na barra de tarefas. Lê data/robo_agora.json (escrito pelo robô) e o banco, a cada segundo.

    pythonw src\\mini.py
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import sqlite3
import sys
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coletor  # noqa: E402
import lojapk  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
AGORA = DADOS / "robo_agora.json"
LOG = DADOS / "robo.log"
BANCO = DADOS / "market.db"
URL_PAINEL = "http://127.0.0.1:8770"
TITULO = "PokeIdle Tracker - status"

# mesmas cores do painel (src/painel/app.css)
MADEIRA, MADEIRA_CLARO, MADEIRA_ESCURO = "#b5654a", "#e3977a", "#6e3424"
LINHA, LINHA_2, BORDA, GRADE = "#2b1d28", "#342431", "#170e15", "#3d2a37"
TINTA, TINTA_2, TINTA_3, CREME = "#f3e9f1", "#c9b6c5", "#8f7a8b", "#fff1d6"
SOBE, DESCE, OURO, GEMA, BOTAO = "#6fd38a", "#ff7b7b", "#f2c14e", "#ff8fd0", "#f2c230"

FASES = {
    "conectando": ("Entrando no jogo", OURO),
    "export": ("Baixando o export", OURO),
    "vitrine": ("Lendo a vitrine", OURO),
    "loja": ("Lendo a loja de Pokémon", GEMA),
    "alertas": ("Conferindo alertas", OURO),
    "esperando": ("Esperando", SOBE),
    "parado": ("Parado", DESCE),
}


# ---------------------------------------------------------------- leitura do estado

def robo_rodando() -> bool:
    """O robô segura um mutex do Windows enquanto roda (ver robo._unico_robo)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, "Local\\PokeIdleTrackerRobo")  # SYNCHRONIZE
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def painel_rodando() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8770), timeout=0.3):
            return True
    except OSError:
        return False


def ler_agora() -> dict:
    try:
        return json.loads(AGORA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def proximos() -> dict[str, float]:
    """Mesma conta de robo.proximos_horarios, lida direto do banco (vale até com o robô parado)."""
    try:
        con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return {}
    try:
        def g(k):
            return coletor.get(con, k)
        return {
            "vitrine": g("vitrine_em") + coletor.VITRINE_A_CADA_MS,
            "export": max(g("export_liberado_em"), g("export_trava_ate")),
            "pokemon": max(g("pokemon_em") + lojapk.INTERVALO_MS, g("pokemon_tentativa_em") + 30 * 60_000),
        }
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def ultima_linha_log() -> str:
    try:
        with open(LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 1500))
            linhas = f.read().decode("utf-8", "replace").strip().splitlines()
        return linhas[-1] if linhas else ""
    except OSError:
        return ""


def falta(ms: float, agora_ms: float) -> str:
    s = (ms - agora_ms) / 1000
    if s <= 0:
        return "agora"
    if s < 60:
        return f"em {int(s)} s"
    m = int(s // 60)
    return f"em {m} min" if m < 60 else f"em {m // 60}h{m % 60:02d}"


def hora(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


# ---------------------------------------------------------------- janela

class Mini(tk.Tk):
    LARG = 330

    def __init__(self):
        super().__init__()
        self.title(TITULO)
        self.configure(bg=MADEIRA_ESCURO)
        self.resizable(False, False)
        self.attributes("-toolwindow", True)   # sem botão na barra de tarefas
        self.attributes("-topmost", True)
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            self.iconbitmap(default="")
        except tk.TclError:
            pass

        f = "Consolas"
        self.f_titulo = (f, 10, "bold")
        self.f_fase = (f, 13, "bold")
        self.f = (f, 10)
        self.f_peq = (f, 9)

        # moldura de madeira, como os quadros do painel
        moldura = tk.Frame(self, bg=MADEIRA, padx=3, pady=3)
        moldura.pack(fill="both", expand=True, padx=2, pady=2)
        cab = tk.Frame(moldura, bg=MADEIRA)
        cab.pack(fill="x", pady=(0, 3))
        self._icone = self._pokebola()
        tk.Label(cab, image=self._icone, bg=MADEIRA).pack(side="left", padx=(2, 6))
        tk.Label(cab, text="POKEIDLE TRACKER", font=self.f_titulo, fg=CREME, bg=MADEIRA).pack(side="left")

        corpo = tk.Frame(moldura, bg=LINHA, padx=10, pady=8, highlightthickness=2,
                         highlightbackground=BORDA)
        corpo.pack(fill="both", expand=True)

        leds = tk.Frame(corpo, bg=LINHA)
        leds.pack(fill="x")
        self.led_robo = self._led(leds, "ROBÔ")
        self.led_painel = self._led(leds, "PAINEL")

        tk.Frame(corpo, bg=GRADE, height=2).pack(fill="x", pady=7)
        tk.Label(corpo, text="AGORA", font=self.f_peq, fg=TINTA_3, bg=LINHA).pack(anchor="w")
        self.fase = tk.Label(corpo, font=self.f_fase, bg=LINHA, anchor="w")
        self.fase.pack(fill="x")
        self.barra = tk.Canvas(corpo, width=self.LARG - 50, height=14, bg=BORDA,
                               highlightthickness=0, bd=0)
        self.det1 = tk.Label(corpo, font=self.f, fg=TINTA, bg=LINHA, anchor="w", justify="left")
        self.det2 = tk.Label(corpo, font=self.f_peq, fg=TINTA_2, bg=LINHA, anchor="w", justify="left",
                             wraplength=self.LARG - 50)
        self.barra.pack(fill="x", pady=(4, 2))
        self.det1.pack(fill="x")
        self.det2.pack(fill="x")

        tk.Frame(corpo, bg=GRADE, height=2).pack(fill="x", pady=7)
        tk.Label(corpo, text="PRÓXIMOS", font=self.f_peq, fg=TINTA_3, bg=LINHA).pack(anchor="w")
        grade = tk.Frame(corpo, bg=LINHA)
        grade.pack(fill="x")
        grade.columnconfigure(0, weight=1)
        self.prox = {}
        for i, (chave, nome) in enumerate((("vitrine", "Vitrine"), ("export", "Export"),
                                            ("pokemon", "Loja Pokémon"))):
            tk.Label(grade, text=nome, font=self.f, fg=TINTA, bg=LINHA, anchor="w").grid(row=i, column=0, sticky="w")
            h = tk.Label(grade, font=self.f, fg=CREME, bg=LINHA, anchor="e")
            em = tk.Label(grade, font=self.f, fg=TINTA_2, bg=LINHA, anchor="e", width=10)
            h.grid(row=i, column=1, sticky="e", padx=(8, 0))
            em.grid(row=i, column=2, sticky="e")
            self.prox[chave] = (h, em)

        tk.Frame(corpo, bg=GRADE, height=2).pack(fill="x", pady=7)
        self.ultimo = tk.Label(corpo, font=self.f_peq, fg=TINTA_3, bg=LINHA, anchor="w", justify="left",
                               wraplength=self.LARG - 50)
        self.ultimo.pack(fill="x")

        botoes = tk.Frame(moldura, bg=MADEIRA)
        botoes.pack(fill="x", pady=(4, 0))
        self._botao(botoes, "Abrir painel", lambda: webbrowser.open(URL_PAINEL), destaque=True).pack(side="left")
        self._botao(botoes, "Log", lambda: os.startfile(LOG)).pack(side="left", padx=4)
        self._botao(botoes, "Fechar", self.destroy).pack(side="right")

        self._cache_prox, self._cache_painel, self._t_lento = {}, False, 0.0
        self.atualizar()
        self._posicionar()

    # -- peças
    def _pokebola(self):
        try:
            from PIL import ImageTk
            import bandeja
            return ImageTk.PhotoImage(bandeja.desenhar_icone().resize((24, 24), 0))
        except Exception:  # noqa: BLE001 - o ícone é só enfeite
            return tk.PhotoImage(width=1, height=1)

    def _led(self, pai, nome):
        q = tk.Frame(pai, bg=LINHA)
        q.pack(side="left", padx=(0, 16))
        led = tk.Canvas(q, width=10, height=10, bg=LINHA, highlightthickness=0)
        led.create_rectangle(1, 1, 9, 9, outline=BORDA, fill=TINTA_3, tags="luz")
        led.pack(side="left", padx=(0, 5))
        txt = tk.Label(q, text=nome, font=self.f_peq, fg=TINTA_2, bg=LINHA)
        txt.pack(side="left")
        return led, txt, nome

    def _botao(self, pai, texto, acao, destaque=False):
        cor, tinta = (BOTAO, "#2a1a08") if destaque else (MADEIRA_CLARO, "#2a1a08")
        return tk.Button(pai, text=texto, command=acao, font=self.f_peq, bg=cor, fg=tinta,
                         activebackground=CREME, relief="flat", bd=0, padx=8, pady=2,
                         highlightthickness=2, highlightbackground=MADEIRA_ESCURO, cursor="hand2")

    def _acender(self, led, ligado, texto):
        canvas, label, nome = led
        canvas.itemconfigure("luz", fill=SOBE if ligado else DESCE)
        label.configure(text=f"{nome}: {texto}")

    def _desenhar_barra(self, frac):
        c = self.barra
        c.delete("all")
        w = int(c.winfo_width() or self.LARG - 50)
        blocos = 24
        bw = (w - 4) / blocos
        cheios = round(max(0.0, min(1.0, frac)) * blocos)
        for i in range(blocos):
            x0 = 2 + i * bw
            c.create_rectangle(x0, 2, x0 + bw - 2, 12, width=0, fill=GEMA if i < cheios else GRADE)

    def _posicionar(self):
        """Canto inferior direito, logo acima da bandeja."""
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        try:  # tamanho de fora, com a barra de título e as bordas
            q = (ctypes.c_long * 4)()
            ctypes.windll.user32.GetWindowRect(int(self.wm_frame(), 16), ctypes.byref(q))
            if q[2] > q[0]:
                w, h = q[2] - q[0], q[3] - q[1]
        except Exception:  # noqa: BLE001
            pass
        try:
            r = (ctypes.c_long * 4)()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
            x, y = r[2] - w - 12, r[3] - h - 12
        except Exception:  # noqa: BLE001
            x, y = self.winfo_screenwidth() - w - 12, self.winfo_screenheight() - h - 90
        self.geometry(f"+{x}+{y}")

    # -- atualização
    def atualizar(self):
        try:
            self._atualizar()
        finally:
            self.after(1000, self.atualizar)

    def _atualizar(self):
        agora_ms = time.time() * 1000
        if time.monotonic() - self._t_lento > 5 or not self._cache_prox:
            self._cache_prox = proximos()
            self._cache_painel = painel_rodando()
            self._t_lento = time.monotonic()

        rodando = robo_rodando()
        a = ler_agora() if rodando else {}
        self._acender(self.led_robo, rodando, "rodando" if rodando else "desligado")
        self._acender(self.led_painel, self._cache_painel, "no ar" if self._cache_painel else "desligado")

        fase = a.get("fase") or ("esperando" if rodando else "parado")
        nome, cor = FASES.get(fase, (fase, TINTA))
        loja = a.get("loja") if fase == "loja" else None
        det1 = det2 = ""
        if not rodando:
            nome, cor = "Robô desligado", DESCE
            det1 = "Use o ícone da bandeja para ligar"
        elif fase == "esperando" and a.get("acordar_ms"):
            det1 = f"próxima checagem às {hora(a['acordar_ms'])} ({falta(a['acordar_ms'], agora_ms)})"
        elif loja:
            total = max(loja.get("total") or 0, loja.get("vistos") or 0, 1)
            vistos = loja.get("vistos") or 0
            seg = max(1.0, (agora_ms - loja.get("inicio_ms", agora_ms)) / 1000)
            resta_s = (total - vistos) / max(vistos / seg, 0.1)
            det1 = f"{vistos:,} de {total:,} anúncios ({vistos / total:.0%})".replace(",", ".")
            det2 = (f"{loja.get('passada', '')} · pág. {loja.get('pagina')}\n"
                    f"começou há {int(seg // 60)}:{int(seg % 60):02d} · faltam ~{max(1, round(resta_s / 60))} min")
        elif a.get("detalhe"):
            det1 = a["detalhe"]
        if a.get("erro") and fase == "esperando":
            det2 = f"última rodada: {a['erro']}"
            cor = DESCE

        self.fase.configure(text=nome, fg=cor)
        if loja:
            if not self.barra.winfo_ismapped():
                self.barra.pack(fill="x", pady=(4, 2), before=self.det1)
            self._desenhar_barra((loja.get("vistos") or 0) / max(loja.get("total") or 1, 1))
        elif self.barra.winfo_ismapped():
            self.barra.pack_forget()
        self.det1.configure(text=det1)
        self.det2.configure(text=det2)
        if det2 and not self.det2.winfo_ismapped():
            self.det2.pack(fill="x", after=self.det1)
        elif not det2 and self.det2.winfo_ismapped():
            self.det2.pack_forget()

        tarefa_atual = {"export": "export", "vitrine": "vitrine", "loja": "pokemon"}.get(fase)
        for chave, (h, em) in self.prox.items():
            ms = self._cache_prox.get(chave)
            if chave == tarefa_atual and rodando:
                h.configure(text="", fg=CREME)
                em.configure(text="rodando", fg=OURO)
            elif ms:
                h.configure(text=hora(max(ms, agora_ms)))
                em.configure(text=falta(ms, agora_ms), fg=TINTA_2)
            else:
                h.configure(text="--:--")
                em.configure(text="")

        ult = ultima_linha_log()
        if ult.startswith("[") and len(ult) > 22:
            ult = f"último registro {ult[12:17]}: {ult[22:]}"
        self.ultimo.configure(text=ult[:150] + ("…" if len(ult) > 150 else ""))

        # A barra e as linhas extras mudam a altura: mantém o canto inferior direito no lugar.
        self.update_idletasks()
        tam = (self.winfo_width(), self.winfo_height())
        if tam != getattr(self, "_tam", None):
            self._tam = tam
            self._posicionar()


# ---------------------------------------------------------------- uma janela só

def trazer_existente() -> bool:
    """Se a janelinha já está aberta, traz para a frente e devolve True."""
    u32 = ctypes.windll.user32
    hwnd = u32.FindWindowW(None, TITULO)
    if not hwnd:
        return False
    u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    u32.SetForegroundWindow(hwnd)
    return True


def main() -> None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k32.CreateMutexW(None, False, "Local\\PokeIdleTrackerMini")  # noqa: F841 - vive até sair
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        trazer_existente()
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texto nítido em telas com escala
    except Exception:  # noqa: BLE001
        pass
    app = Mini()
    app.focus_force()
    app.mainloop()


if __name__ == "__main__":
    main()
