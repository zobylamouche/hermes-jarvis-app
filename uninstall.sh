#!/usr/bin/env bash
# Jarvis Bot — désinstallation propre (garde le token et les logs par défaut)
set -euo pipefail
PREFIX="${1:-/opt/jarvis}"
UNIT_NAME="jarvis-bot"

systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${UNIT_NAME}.service"
systemctl daemon-reload

if [ "${1:-}" != "--purge" ]; then
  echo "→ Service supprimé. $PREFIX conservé (token, logs)."
  echo "  Pour tout effacer : sudo ./uninstall.sh --purge"
else
  echo "⚠️  Suppression totale de $PREFIX (token, logs, code) dans 3 s… Ctrl+C pour annuler"
  sleep 3
  rm -rf "$PREFIX"
  echo "→ Effacé."
fi