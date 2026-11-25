#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
PY="$HOME/myr-venv/bin/python"
"$PY" -B vps/backend/native_record_writes.py
bash vps/setup-hybrid-preview.sh
"$PY" -B vps/backend/hybrid_write_test.py
"$PY" -B vps/backend/build_write_preview.py
systemctl --user restart myr-preview.service
for i in {1..15}; do
 if curl -fsS --max-time 2 http://127.0.0.1:8765/health >/dev/null 2>&1; then break; fi
 sleep 1
done
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsS http://127.0.0.1:8765/website-write/ -o "$tmp"
grep -Fq 'PRIVATE VPS WRITE TEST' "$tmp"
if command -v node >/dev/null; then
 "$PY" -B - "$tmp" <<'PYCODE'
import re,sys,subprocess
from pathlib import Path
html=Path(sys.argv[1]).read_text()
for attrs,code in re.findall(r'<script([^>]*)>(.*?)</script>',html,re.S|re.I):
    if code.strip() and 'application/ld+json' not in attrs and 'application/json' not in attrs:
        subprocess.run(["node","--check","-"],input=code,text=True,check=True)
print("VPS_PREVIEW_JS_SYNTAX_OK")
PYCODE
fi
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/hybrid/write-workspace)" = 401
test "$(curl -sS -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"p_company_id":"00000000-0000-0000-0000-000000000000","p_kind":"customers","p_record":{}}' http://127.0.0.1:8765/hybrid/test-record)" = 401
echo "VPS_SYNTHETIC_UI_WRITE_PREVIEW_READY"
echo "Browser acceptance required: /website-write/; real company data remains read-only at /website/."
echo "Payments, other mutations, email, LHDN, public HTTPS and cutover remain disabled."
