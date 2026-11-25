#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
bash vps/prepare-staging.sh
bash vps/http-smoke.sh
"$HOME/myr-venv/bin/python" -B vps/backend/check_native_auth.py
"$HOME/myr-venv/bin/python" -B vps/backend/check_staging_api.py
echo "VPS_APPLICATION_STAGE_1_OK"
echo "Local tests only; signup, email, migration, frontend and production deployment remain disabled."
