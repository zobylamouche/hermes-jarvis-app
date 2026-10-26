#!/usr/bin/env bash
# Mémoire de Jarvis : synchronisation DIRECTE entre machines — jamais via git.
# Usage (depuis une machine où Jarvis est installé) :
#   sudo ./sync_memoire.sh push root@autre-hermes   → envoyer MA mémoire sur l'autre machine
#   sudo ./sync_memoire.sh pull root@autre-hermes   → récupérer la mémoire de l'autre machine
set -euo pipefail

JARVIS_DIR="${JARVIS_DIR:-/opt/jarvis}"
FILE="$JARVIS_DIR/data/jarvis_memoire.md"
CMD="${1:-}"; DEST="${2:-}"

case "$CMD" in
  push)
    [ -f "$FILE" ] || { echo "Pas de mémoire locale ($FILE) — rien à envoyer."; exit 1; }
    rsync -av "$FILE" "$DEST:$FILE"
    echo "→ Mémoire envoyée à $DEST"
    ;;
  pull)
    [ -n "$DEST" ] || { echo "Usage: $0 {push|pull} utilisateur@hôte"; exit 1; }
    rsync -av "$DEST:$FILE" "$FILE"
    echo "→ Mémoire récupérée depuis $DEST"
    ;;
  *)
    echo "Usage: $0 {push|pull} utilisateur@hôte"
    exit 1
    ;;
esac

echo "Pas de restart nécessaire : Jarvis recharge la mémoire à chaque réponse."