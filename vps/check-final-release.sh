#!/usr/bin/env bash
# Single read-only release rehearsal; never updates production data or deployment markers.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/myr-venv/bin/python"
test -x "$PY" || exit 2
fail=0
run(){ printf '\n--- %s ---\n' "$1"; shift; if "$@"; then echo PASS; else echo FAIL; fail=1; fi; }
run "CHIP protocol and callback mocks" node supabase/functions/myr-chip-payment/check_release.mjs
run "CHIP disposable ledger" bash vps/check-chip-disposable-db.sh
run "Billing view" "$PY" -B vps/backend/chip_billing_view_candidate.py
run "Billing UI integration build" "$PY" -B vps/backend/build_chip_billing_candidate.py
run "Subscription renewal policy" "$PY" -B vps/backend/chip_subscription_policy_candidate.py
run "Manual billing disposable ledger" bash vps/check-billing-disposable-db.sh
run "Production read-only preflight" "$PY" -B vps/backend/check_launch_preflight.py
if [ "${1:-}" = --test-email ]; then
  run "Post-DNS single support inbox email" "$PY" -B vps/backend/check_email_after_dns.py
fi
echo "Actual CHIP paid sandbox transaction, LHDN provider acceptance, verified email delivery, merchant approval and live billing are independent launch gates."
if [ "$fail" -ne 0 ]; then echo MYR_CONSOLIDATED_REHEARSAL_FAILED; exit 1; fi
echo MYR_CONSOLIDATED_REHEARSAL_OK
