#!/usr/bin/env bash
# One consolidated, read-only live preflight plus synthetic private rehearsals.
# No live migrations or writes, no provider login/submit, no deployment.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -u)" -ne 0
PY="$HOME/myr-venv/bin/python"
test -x "$PY"
bash vps/check-lhdn-offline-suite.sh
bash vps/check-lhdn-disposable-db.sh
bash vps/prepare-lhdn-isolated-sandbox.sh --rehearse
"$PY" -B vps/backend/check_pilot_preflight.py
echo "MYR_INTERNAL_PREPARATION_CHECKS_OK"
echo "Connection prerequisites only. Real authorization, isolated service deployment, official provider acceptance and production release are NOT verified."
