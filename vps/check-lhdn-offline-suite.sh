#!/usr/bin/env bash
# Offline test suite only. No DB, credential, provider, or production calls.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$HOME/myr-venv/bin/python"
DENO="$HOME/.deno/bin/deno"
test -x "$PY" && test -x "$DENO"
for file in lhdn_protocol_candidate.py lhdn_ubl_candidate.py lhdn_saved_invoice_candidate.py lhdn_lifecycle_candidate.py lhdn_readiness_candidate.py lhdn_sandbox_poll_candidate.py lhdn_direct_candidate.py; do
    echo "=== $file ==="
    env -u MYR_PRODUCTION_RELEASE "$PY" -B "vps/backend/$file"
done
echo "=== Edge connector type checking and mock tests ==="
"$DENO" test --no-prompt supabase/functions/myr-lhdn-intermediary/index_test.ts supabase/functions/myr-lhdn-intermediary/sandbox_transport_candidate_test.ts supabase/functions/myr-lhdn-intermediary/sandbox_dispatch_bridge_candidate_test.ts
echo "=== Signing candidate dependency check ==="
if ! "$PY" -B -c 'import cryptography; from cryptography import x509; assert hasattr(x509.Certificate,"not_valid_before_utc"); print("cryptography",cryptography.__version__)'; then
    echo "MYR_SIGNING_DEPENDENCY_REVIEW_REQUIRED"
    echo "Non-signing tests passed; signing tests not executed. No package installed."
    exit 2
fi
env -u MYR_PRODUCTION_RELEASE "$PY" -B vps/backend/lhdn_signing_candidate.py
env -u MYR_PRODUCTION_RELEASE "$PY" -B vps/backend/lhdn_direct_vault_candidate.py
env -u MYR_PRODUCTION_RELEASE "$PY" -B vps/backend/lhdn_direct_pilot_candidate.py
echo "MYR_LHDN_OFFLINE_SUITE_OK"
echo "Mock/offline only; DB rehearsal, official authorization, signature interoperability and provider acceptance are not verified."
