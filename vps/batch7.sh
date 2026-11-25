#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash vps/next-batch.sh
bash vps/prepare-offsite.sh
echo "VPS_PROFILE_NUMBERING_AND_EXPORT_BATCH_OK"
echo "Browser testing, remaining business functions, offsite destination, production HTTPS and cutover are still pending."
