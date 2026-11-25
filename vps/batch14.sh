#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"$HOME/myr-venv/bin/python" -B vps/backend/native_team_workflow.py
bash vps/setup-write-preview.sh
for endpoint in test-team test-approval; do
 if [ "$endpoint" = test-team ]; then
  body='{"p_company_id":"00000000-0000-0000-0000-000000000000","p_operation":"invite","p_email":"test@example.invalid","p_role":"Read-Only"}'
 else
  body='{"p_company_id":"00000000-0000-0000-0000-000000000000","p_invoice_id":"test","p_version":1,"p_action":"request"}'
 fi
 test "$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$body" "http://127.0.0.1:8765/hybrid/$endpoint")" = 401
done
bash vps/batch8.sh
echo "VPS_PRIVATE_WORKFLOW_API_READY"
echo "Authenticated workflow acceptance, UI, real onboarding, invitations and production deployment remain pending."
