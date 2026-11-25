#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
"$PY" -B vps/backend/verify_stage_copy.py
"$PY" -B vps/backend/check_staging_api.py
"$PY" -B - <<'PYCODE'
import sys
sys.path.insert(0,"vps/backend")
from private_preview import preview
page=preview()
assert page.status_code==200 and b"Read-only" in page.body
assert "connect-src 'self'" in page.headers["content-security-policy"]
print("PRIVATE_PREVIEW_CODE_OK")
PYCODE
echo "VPS_POST_MIGRATION_CHECKS_OK"
echo "No customer records changed; preview not started or publicly exposed."
