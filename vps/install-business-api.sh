#!/usr/bin/env bash
set -euo pipefail
test "$(id -un)" = myradmin
cd "$HOME/myr-invoices"
PY="$HOME/myr-venv/bin/python"
"$PY" -B vps/backend/business_api.py
units="$HOME/.config/systemd/user"
mkdir -p "$units"
cat >"$units/myr-business-api.service" <<'UNIT'
[Unit]
Description=MYR Invoice business API candidate (private loopback)
After=network-online.target
[Service]
Type=simple
WorkingDirectory=%h/myr-invoices/vps/backend
ExecStart=%h/myr-venv/bin/python -B -m uvicorn business_api:api --host 127.0.0.1 --port 8766 --no-proxy-headers
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
UMask=0077
[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now myr-business-api.service
systemctl --user restart myr-business-api.service
for i in {1..15}; do
  if curl -fsS --max-time 2 http://127.0.0.1:8766/health; then break; fi
  sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:8766/health | "$PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"] is False'
test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8766/workspace)" = 401
test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"p_company_id":"00000000-0000-0000-0000-000000000000","p_kind":"customers","p_record":{}}' http://127.0.0.1:8766/records)" = 401
echo
echo "MYR_BUSINESS_API_CANDIDATE_READY"
echo "No Nginx proxy configured. Production writes disabled. Live Supabase data unchanged."
