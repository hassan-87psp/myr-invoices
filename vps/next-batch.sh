#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash vps/setup-write-preview.sh
bash vps/check-private-security.sh
echo "VPS_EXTENDED_PRIVATE_BATCH_OK"
echo "Browser acceptance, remaining business operations, offsite backup and public cutover are NOT complete."
