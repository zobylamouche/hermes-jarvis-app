#!/usr/bin/env bash
# Jarvis Bot — installation sur n'importe quelle machine / instance Hermes
# Usage : sudo ./install.sh [préfixe]     (défaut : /opt/jarvis)
set -euo pipefail

PREFIX="${1:-/opt/jarvis}"
SRC="$(cd "$(dirname "$0")" && pwd)"
UNIT_NAME="jarvis-bot"

echo "→ Installation Jarvis Bot dans $PREFIX"
mkdir -p "$PREFIX/data" "$PREFIX/models/piper"

# 1. fichiers (bot.py, jarvis_brain.py, app/, README) sauf .env, data et venv (jamais écrasés)
[ "$SRC" != "$PREFIX" ] && install -m 755 "$SRC/bot.py" "$PREFIX/bot.py" || true
[ "$SRC" != "$PREFIX" ] && [ -f "$SRC/jarvis_brain.py" ] && install -m 755 "$SRC/jarvis_brain.py" "$PREFIX/jarvis_brain.py" || true
if [ "$SRC" != "$PREFIX" ] && [ -d "$SRC/app" ]; then
  mkdir -p "$PREFIX/app"
  cp -r "$SRC/app/server.py" "$PREFIX/app/server.py"
  [ -d "$SRC/app/static" ] && cp -r "$SRC/app/static/." "$PREFIX/app/static/" || true
fi
[ "$SRC" != "$PREFIX" ] && [ -f "$SRC/README.md" ] && install -m 644 "$SRC/README.md" "$PREFIX/README.md" || true
[ "$SRC" != "$PREFIX" ] && [ -d "$SRC/models/piper" ] && cp -n "$SRC/models/piper/"*.onnx* "$PREFIX/models/piper/" 2>/dev/null || true

# 2. .env : créé une seule fois, jamais écrasé par une réinstallation
if [ ! -f "$PREFIX/.env" ]; then
  cat > "$PREFIX/.env" <<'EOF'
# --- Jarvis Bot configuration ---
# Token du bot (via @BotFather -> /newbot). JAMAIS en clair dans un chat.
TELEGRAM_BOT_TOKEN=
# Chat ids autorisés (virgules pour plusieurs) : le chat où tu parles à ton Hermes
ALLOWED_CHAT_IDS=7981177449
# Chemin du binaire hermes (auto-détecté si vide)
HERMES_BIN=
# Timeout d'un appel cerveau en secondes
JARVIS_TIMEOUT_BRAIN=240
EOF
  chmod 600 "$PREFIX/.env"
  echo "⚠️  $PREFIX/.env créé — remplis TELEGRAM_BOT_TOKEN avant de démarrer."
else
  chmod 600 "$PREFIX/.env"
  echo "→ .env existant conservé."
fi

# 3. environnement python dédié (fastapi, uvicorn, faster-whisper)
if [ ! -x "$PREFIX/venv/bin/python3" ]; then
  echo "→ Création du venv Python + dépendances (quelques minutes)…"
  python3 -m venv "$PREFIX/venv"
  "$PREFIX/venv/bin/pip" -q install fastapi uvicorn python-multipart faster-whisper piper-tts
else
  echo "→ venv existant conservé."
fi

# 4. détection du binaire hermes (pour le PATH du service)
HERMES_PATH="$(command -v hermes 2>/dev/null || echo /usr/local/lib/hermes-agent/.hermes/bin/hermes)"
HERMES_DIR="$(dirname "$HERMES_PATH")"

# 5. unité systemd — le bot + la Mini App
cat > "/etc/systemd/system/${UNIT_NAME}.service" <<EOF
[Unit]
Description=Jarvis Bot (Telegram -> Hermes)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$PREFIX/venv/bin/python3 $PREFIX/bot.py
Restart=always
RestartSec=10
Environment=HOME=\$HOME
Environment=PATH=$HERMES_DIR:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=$PREFIX

[Install]
WantedBy=multi-user.target
EOF

cat > "/etc/systemd/system/jarvis-app.service" <<EOF
[Unit]
Description=Jarvis Mini App (FastAPI, HUD Telegram)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$PREFIX/venv/bin/python3 $PREFIX/app/server.py
Restart=always
RestartSec=10
Environment=HOME=\$HOME
Environment=PATH=$HERMES_DIR:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=$PREFIX/app

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "✅ Installé (bot + Mini App)."
echo "   1) Remplis TELEGRAM_BOT_TOKEN dans $PREFIX/.env (chmod 600)"
echo "   2) systemctl enable --now jarvis-bot jarvis-app"
echo "   3) nginx : proxy du sous-domaine Mini App vers 127.0.0.1:8010 + certbot --nginx"
echo "   4) Envoie /start à ton bot, puis bouton 'OUVRIR JARVIS'"