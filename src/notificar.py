"""Canais de notificação dos alertas. Configuração no config.local.json, bloco "alertas":

    "alertas": {
      "windows": true,                       # notificação nativa do Windows (só no PC)
      "discord_webhook": "https://discord.com/api/webhooks/...",   # opcional
      "telegram_token": "123:ABC...", "telegram_chat_id": "123456" # opcional
    }

Sem configuração nenhuma: no Windows usa a notificação nativa; em qualquer lugar, grava no log.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path  # noqa: F401

import caminhos

CONFIG = caminhos.CONFIG
USER_AGENT = "pokeidletracker-alertas/1.0"


def config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8")).get("alertas") or {}
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg.setdefault("windows", os.name == "nt")
    return cfg


def canais_ativos(cfg: dict | None = None) -> list[str]:
    cfg = config() if cfg is None else cfg
    c = []
    if cfg.get("windows") and os.name == "nt":
        c.append("windows")
    if cfg.get("discord_webhook"):
        c.append("discord")
    if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
        c.append("telegram")
    return c


def _windows(titulo: str, texto: str) -> None:
    # Toast nativo pelo PowerShell (sem instalar nada). O texto vai em base64 para não ser
    # interpretado pelo PowerShell; o AppID é o do próprio PowerShell, que o Windows já reconhece.
    b = lambda s: base64.b64encode(s.encode("utf-8")).decode()  # noqa: E731
    script = f"""
$t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b(titulo)}'))
$m = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b(texto)}'))
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x.GetElementsByTagName('text')[0].AppendChild($x.CreateTextNode($t)) > $null
$x.GetElementsByTagName('text')[1].AppendChild($x.CreateTextNode($m)) > $null
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                   check=True, capture_output=True, timeout=20,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _post_json(url: str, corpo: dict) -> None:
    req = urllib.request.Request(url, json.dumps(corpo).encode(), {"Content-Type": "application/json",
                                                                    "User-Agent": USER_AGENT})
    urllib.request.urlopen(req, timeout=15).read()


def _discord(url: str, texto: str) -> None:
    _post_json(url, {"username": "PokeIdle Tracker", "content": texto[:1900]})


def _telegram(token: str, chat: str, texto: str) -> None:
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/sendMessage"
    _post_json(url, {"chat_id": chat, "text": texto[:4000], "disable_web_page_preview": True})


def enviar(titulo: str, texto: str, cfg: dict | None = None) -> tuple[list[str], list[str]]:
    """Manda para todos os canais configurados. Devolve (canais que deram certo, erros)."""
    cfg = config() if cfg is None else cfg
    ok, erros = [], []
    for canal in canais_ativos(cfg):
        try:
            if canal == "windows":
                _windows(titulo, texto)
            elif canal == "discord":
                _discord(cfg["discord_webhook"], f"**{titulo}**\n{texto}")
            elif canal == "telegram":
                _telegram(cfg["telegram_token"], str(cfg["telegram_chat_id"]), f"{titulo}\n{texto}")
            ok.append(canal)
        except Exception as e:  # um canal com problema não derruba os outros
            erros.append(f"{canal}: {e!r}"[:200])
    return ok, erros
