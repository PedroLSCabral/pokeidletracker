"""Onde fica cada coisa do projeto, num lugar só.

Todo módulo que precisa de uma pasta ou arquivo do projeto importa daqui, em vez de calcular a partir
do próprio `__file__` (o que quebrava a cada arquivo movido de pasta).
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent
RAIZ = SRC.parent

# Configuração local (nick e token da conta coletora, canais de alerta). Nunca vai para o git.
CONFIG = RAIZ / "config.local.json"

# Dados gerados em tempo de execução (fora do git).
DADOS = RAIZ / "data"
BANCO = DADOS / "market.db"            # SQLite com vendas, vitrine, loja de Pokémon, alertas e cache do PvP
LOG_ROBO = DADOS / "robo.log"          # o que o robô fez (export, vitrine, alertas, quedas)
AGORA_ROBO = DADOS / "robo_agora.json"  # o que o robô está fazendo agora (lido pela janelinha de status)
JOGO = DADOS / "jogo"                  # dados do jogo para a conta de XP/h (analise/caca.py)
CATALOGO_JOGO = JOGO / "catalogo.json"     # espécies, stats-base e golpes (dos assets públicos, 1 vez por dia)
WELCOME_JOGO = JOGO / "welcome-dados.json"  # hunts e constantes de caça, tirados do welcome a cada login

# Página do painel (HTML/CSS/JS servidos pelo painel.py).
WEB = SRC / "web"

# Primeira tentativa de coleta, por userscript no navegador (fica como alternativa).
LEGADO = RAIZ / "legado"
USERSCRIPT = LEGADO / "userscript" / "pokeidle-coletor.user.js"
