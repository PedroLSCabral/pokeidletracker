"""Visual compartilhado pelas janelas Tk (status e menu da bandeja) e pelo ícone da bandeja.

As cores e as fontes são as do jogo, as mesmas de src/web/app.css: madeira, botão roxo e vão
escuro; texto em Segoe UI e títulos em Tahoma negrito com contorno.
"""
from __future__ import annotations

# madeira
MAD_LINHA = "#480e1e"   # filete escuro, o mais externo
MAD_LUZ = "#f1d3b7"     # brilho de cima
MAD_LUZ2 = "#e7a86d"    # brilho dos botões
MAD = "#bd6951"         # corpo
MAD_ESC = "#914850"
MAD_QUENTE = "#df824c"
MAD_BASE = "#722c3f"    # degrau de baixo e contorno do texto
# roxo dos botões ligados
RX_LUZ, RX_ESC, RX, RX_CLR = "#ffdef0", "#8d49b8", "#ba5ad1", "#e77ad2"
# vãos
VAO, VAO2, VAO_LUZ = "#33202b", "#462b39", "#5c3948"
# texto
TINTA, TINTA_2, TINTA_3 = "#fff6ef", "#ead7df", "#c9a9b4"
SOBRE_MAD_DIM = "#f5cdb9"
CREME = "#ffe9c9"
SOBE, DESCE, OURO, GEMA = "#6fd08a", "#ff8f80", "#f7c75a", "#ff9ad6"

TEXTO = "Segoe UI"
TITULO = "Tahoma"

# O que o robô está fazendo (campo "fase" de data/robo_agora.json): texto e cor.
FASES = {
    "conectando": ("Entrando no jogo", OURO),
    "export": ("Baixando o export", OURO),
    "vitrine": ("Lendo a vitrine", OURO),
    "loja": ("Lendo a loja de Pokémon", GEMA),
    "alertas": ("Conferindo alertas", OURO),
    "esperando": ("Esperando", SOBE),
    "parado": ("Parado", DESCE),
}


def desenhar_pokebola(lado: int = 64):
    """Pokébola em pixel art 16x16, ampliada sem suavizar (ícone da bandeja e das janelas)."""
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
    return img.resize((lado, lado), Image.NEAREST)


def moldura(tk, pai, **pack):
    """Quadro de madeira com os filetes do jogo (escuro, brilho, corpo). Devolve o miolo de madeira."""
    fora = tk.Frame(pai, bg=MAD_LINHA, padx=2, pady=2)
    fora.pack(fill="both", expand=True, **pack)
    luz = tk.Frame(fora, bg=MAD_LUZ, padx=2, pady=2)
    luz.pack(fill="both", expand=True)
    corpo = tk.Frame(luz, bg=MAD, padx=8, pady=6)
    corpo.pack(fill="both", expand=True)
    tk.Frame(luz, bg=MAD_QUENTE, height=3).pack(fill="x", side="bottom")  # reflexo de baixo
    return corpo


def vao(tk, pai, padx=10, pady=8, **pack):
    """Vão escuro recuado dentro da madeira, com o filete escuro em volta."""
    fora = tk.Frame(pai, bg=MAD_LINHA, padx=2, pady=2)
    fora.pack(fill="both", expand=True, **pack)
    dentro = tk.Frame(fora, bg=VAO, padx=padx, pady=pady)
    dentro.pack(fill="both", expand=True)
    return dentro


def titulo_contornado(tk, pai, texto: str, tamanho: int = 10, bg: str = MAD):
    """Título em Tahoma negrito branco com contorno escuro de 4 pontos, como os do jogo."""
    from tkinter import font as tkfont
    f = tkfont.Font(family=TITULO, size=tamanho, weight="bold")
    w, h = f.measure(texto) + 6, f.metrics("linespace") + 4
    c = tk.Canvas(pai, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2), (2, 0), (-2, 0), (0, -2)):
        c.create_text(3 + dx, h // 2 + dy, text=texto, font=f, fill=MAD_BASE, anchor="w")
    c.create_text(3, h // 2, text=texto, font=f, fill="#ffffff", anchor="w")
    c._fonte = f  # segura a fonte viva junto com o canvas
    return c
