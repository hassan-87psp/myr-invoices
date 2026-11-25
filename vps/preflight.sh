#!/usr/bin/env bash
# Read-only staging preflight. No credentials stored, no network listeners.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
"$PY" -B -c 'import sys; sys.path.insert(0, "vps/backend"); from app import app; assert any(r.path == "/health" for r in app.routes); print("BACKEND_IMPORT_OK")'
psql -h 127.0.0.1 -U myrinvoice_app -d myrinvoice -v ON_ERROR_STOP=1 -c 'SELECT current_database(), current_user;'
echo "VPS_PREFLIGHT_OK"
echo "Backend imported, database verified. API service, auth, migration and email are not configured yet."
