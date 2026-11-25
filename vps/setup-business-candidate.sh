#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/myr-invoices"
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
# Build from the already-installed private synthetic UI; never touch public files.
"$PY" -B vps/backend/build_business_candidate.py
"$PY" -B - "$HOME/myr-staging/business-candidate/index.html" <<'PYCODE'
import re,sys,subprocess
from pathlib import Path
html=Path(sys.argv[1]).read_text()
for attrs,code in re.findall(r'<script([^>]*)>(.*?)</script>',html,re.S|re.I):
    if code.strip() and 'application/ld+json' not in attrs and 'application/json' not in attrs:
        subprocess.run(["node","--check","-"],input=code,text=True,check=True)
print("MYR_BUSINESS_FRONTEND_JS_OK")
PYCODE
"$PY" -B vps/backend/check_business_asgi.py
"$PY" -B vps/backend/business_admin.py
bash vps/install-business-api.sh
base=http://127.0.0.1:8766
curl -fsS --max-time 10 "$base/candidate/" | grep -F 'PRIVATE VPS DATABASE CANDIDATE' >/dev/null
test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$base/workspace")" = 401
for path in onboard profile; do
 if [ "$path" = onboard ]; then
  data='{"p_profile":{}}'
 else
  data='{"p_company_id":"00000000-0000-0000-0000-000000000000","p_version":1,"p_profile":{}}'
 fi
 test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$data" "$base/$path")" = 401
done
echo "MYR_BUSINESS_FRONTEND_CANDIDATE_READY"
echo "Use SSH forwarding of port 8766. Imported real data read-only. No public deployment or source data changes."
