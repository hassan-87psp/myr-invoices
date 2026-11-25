#!/usr/bin/env bash
# Interactive private preview. Stop with Ctrl+C. No public listener.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
"$PY" -B vps/backend/activate_staging_owner.py
echo "Private preview port 8765. Access through localhost SSH forwarding only."
exec "$PY" -B -m uvicorn private_preview:api --app-dir vps/backend --host 127.0.0.1 --port 8765 --no-proxy-headers --no-access-log
