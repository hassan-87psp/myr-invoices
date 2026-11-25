#!/usr/bin/env bash
# Single operator preflight. No production changes or source write freeze.
set -euo pipefail
cd "$HOME/myr-invoices"
PY="$HOME/myr-venv/bin/python"
"$PY" -B vps/backend/build_cutover_check.py
"$PY" -B vps/backend/reconcile_business.py "$@"
for test in check_business_asgi.py business_admin.py business_links.py business_link_ops.py business_api.py; do
  "$PY" -B "vps/backend/$test"
done
"$PY" -B - <<'PYCODE'
from urllib.request import urlopen
import json
with urlopen("http://127.0.0.1:8766/health",timeout=5) as r:
    h=json.load(r)
assert h["database"]=="vps" and h["writes_enabled"] is False
print("MYR_PRIVATE_API_HEALTH_OK")
PYCODE
systemctl --user is-active myr-candidate-deploy.timer
systemctl --user is-active myr-native-backup.timer
echo "MYR_BUSINESS_CUTOVER_PREFLIGHT_OK"
echo "Point-in-time rehearsal only: public link state, full feature parity, source freeze and production routing still require acceptance."
