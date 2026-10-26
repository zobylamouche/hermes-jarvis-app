#!/usr/bin/env bash
# Jarvis — désinstallation propre (garde le token et les logs par défaut)
# Usage : sudo ./uninstall.sh [--purge] [préfixe]   (défaut : /opt/jarvis)
set -euo pipefail

PURGE=0
PREFIX="/opt/jarvis"
for a in "$@"; do
  case "$a" in
    --purge) PURGE=1 ;;
    *) PREFIX="$a" ;;
  esac
done

systemctl disable --now jarvis-bot 2>/dev/null || true
systemctl disable --now jarvis-app 2>/dev/null || true
rm -f /etc/systemd/system/jarvis-bot.service /etc/systemd/system/jarvis-app.service
systemctl daemon-reload

if [ "$PURGE" != "1" ]; then
  echo "→ Services supprimés. $PREFIX conservé (token, logs, modèles)."
  echo "  Pour tout effacer : sudo ./uninstall.sh --purge"
else
  echo "⚠️  Suppression totale de $PREFIX (token, logs, code, modèles) dans 3 s… Ctrl+C pour annuler"
  sleep 3
  rm -rf "$PREFIX"
  echo "→ Effacé."
fi