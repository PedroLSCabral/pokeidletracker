@echo off
title Coletor PokeIdle
cd /d "%~dp0.."
echo Coletor PokeIdle - deixe esta janela aberta. Status: http://127.0.0.1:8765
python src\coleta\coletor.py
pause
