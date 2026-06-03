#!/bin/bash
# Deploy server.py to the machine being controlled, then (re)start it.
#
# Usage:
#   ./deploy_server.sh user@host [--port 5901] [--password secret] [--display :0]
#
# Requires SSH access to the target. You'll be prompted for its password unless
# you have key-based auth set up.

set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "Usage: $0 user@host [--port N] [--password PW] [--display :0]" >&2
    exit 1
fi
shift

PORT=5901
PASSWORD=""
DISPLAY_VAR=":0"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)     PORT="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        --display)  DISPLAY_VAR="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

SRC="$(cd "$(dirname "$0")" && pwd)/server.py"
echo "→ Copying server.py to $TARGET:~/remote_control/server.py"
ssh "$TARGET" 'mkdir -p ~/remote_control'
scp "$SRC" "$TARGET:~/remote_control/server.py"

PW_ARG=""
[[ -n "$PASSWORD" ]] && PW_ARG="--password $PASSWORD"

echo "→ Restarting server on $TARGET (port $PORT, DISPLAY=$DISPLAY_VAR)"
ssh "$TARGET" "pkill -f '[s]erver\\.py --port' 2>/dev/null || true; \
  DISPLAY=$DISPLAY_VAR setsid nohup python3 ~/remote_control/server.py \
  --port $PORT $PW_ARG </dev/null >~/remote_control/server.log 2>&1 & \
  sleep 1; echo started"

echo "✓ Done. Logs: $TARGET:~/remote_control/server.log"
