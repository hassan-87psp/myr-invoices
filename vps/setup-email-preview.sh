#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
bash vps/check-migrated.sh
"$PY" -B - <<'PYCODE'
import sys,ssl,socket
sys.path.insert(0,"vps/backend")
from admin_email import DEFAULTS,render
assert len(DEFAULTS)==11
assert "&lt;script&gt;" in render("<script>","Test")
print("EMAIL_TEMPLATE_SMOKE_OK")
host="preprod-api.myinvois.hasil.gov.my"
try:
    with socket.create_connection((host,443),timeout=8) as sock:
        with ssl.create_default_context().wrap_socket(sock,server_hostname=host):
            print("LHDN_SANDBOX_TLS_OK")
except OSError:
    print("LHDN_SANDBOX_TLS_UNVERIFIED: check connectivity and trust")
PYCODE
echo "VPS_EMAIL_ADMIN_STAGE_READY"
exec "$PY" -B -m uvicorn private_preview:api --app-dir vps/backend --host 127.0.0.1 --port 8765 --no-proxy-headers --no-access-log
