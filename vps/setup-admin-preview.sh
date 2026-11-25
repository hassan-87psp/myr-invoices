#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
bash vps/check-migrated.sh
"$PY" -B vps/backend/finalize_staging_admin.py
echo "VPS_ADMIN_STAGE_READY"
echo "Private preview starting on 127.0.0.1:8765; use an SSH tunnel. No DNS change."
exec "$PY" -B -m uvicorn private_preview:api --app-dir vps/backend --host 127.0.0.1 --port 8765 --no-proxy-headers --no-access-log
