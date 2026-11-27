#!/usr/bin/env bash
# Private integration rehearsal. No production database or LHDN provider requests.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/myr-venv/bin/python"
test -x "$PY"
unset MYR_PRODUCTION_RELEASE
bash vps/check-lhdn-offline-suite.sh
echo "=== Sandbox HTTP transport mock tests ==="
"$HOME/.deno/bin/deno" test supabase/functions/myr-lhdn-intermediary/sandbox_transport_candidate_test.ts
for f in lhdn_worker_rehearsal.py lhdn_rejection_candidate.py lhdn_xades_rehearsal.py lhdn_readiness_route_candidate.py; do
    echo "=== $f ==="
    "$PY" -B "vps/backend/$f"
done
echo "=== Disposable database rehearsal ==="
bash vps/check-lhdn-disposable-db.sh
echo "=== Private candidate UI syntax ==="
"$PY" -B vps/backend/build_native_auth_candidate.py
"$PY" -B vps/backend/build_lhdn_readiness_candidate.py
echo "MYR_LHDN_PRIVATE_INTEGRATION_SUITE_OK"
echo "No real document sent. No production release, full-schema test, trusted certificate, browser acceptance or official provider acceptance implied."
