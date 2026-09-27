#!/usr/bin/env bash
# Panel BNC para macOS / Linux. Uso: ./iniciar_panel.sh
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/listo.txt ]; then
  echo "Preparando el bot por primera vez. Tarda unos minutos..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m playwright install chromium
  echo ok > .venv/listo.txt
fi
[ -f .env ] || cp .env.example .env
echo "Panel en http://127.0.0.1:8765  (deja esta ventana abierta; Ctrl+C para cerrar)"
exec .venv/bin/python -m bnc_bot.panel
