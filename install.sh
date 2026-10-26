#!/usr/bin/env bash
# Jarvis Bot — installation sur n'importe quelle machine / instance Hermes
# Usage : sudo ./install.sh [préfixe]     (défaut : /opt/jarvis)
set -euo pipefail

PREFIX="${1:-/opt/jarvis}"
SRC="$(cd "$(dirname "$0")" && pwd)"
UNIT_NAME="jarvis-bot"

echo "→ Installation Jarvis Bot dans $PREFIX"
mkdir -p "$PREFIX/data"

# 1. fichiers (bot.py, README) sauf .env et data (jamais écrasés)
[ "$SRC" != "$PREFIX" ] && install -m 755 "$SRC/bot.py" "$PREFIX/bot.py"
[ "$SRC" != "$PREFIX" ] && [ -f "$SRC/README.md" ] && install -m 644 "$SRC/README.md" "$PREFIX/README.md" || true

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

# 3. détection du binaire hermes (pour le PATH du service)
HERMES_PATH="$(command -v hermes 2>/dev/null || echo /usr/local/lib/hermes-agent/.hermes/bin/hermes)"
HERMES_DIR="$(dirname "$HERMES_PATH")"

# 4. unité systemd
cat > "/etc/systemd/system/${UNIT_NAME}.service" <<EOF
[Unit]
Description=Jarvis Bot (Telegram -> Hermes)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$(command -v python3 || echo /usr/bin/python3) $PREFIX/bot.py
Restart=always
RestartSec=10
Environment=HOME=\$HOME
Environment=PATH=$HERMES_DIR:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=$PREFIX

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "✅ Installé."
echo "   1) Remplis TELEGRAM_BOT_TOKEN dans $PREFIX/.env (chmod 600)"
echo "   2) systemctl enable --now $UNIT_NAME"
echo "   3) Envoie /start à ton bot dans Telegram"