@echo off
rem Liga o robo e o painel escondidos, com um icone na bandeja (perto do relogio), e abre o painel.
rem Se ja estiverem ligados, so abre o painel.
cd /d "%~dp0"
start "" pythonw src\bandeja.py --abrir
