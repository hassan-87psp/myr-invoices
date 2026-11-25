#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"$HOME/myr-venv/bin/python" -B vps/backend/check_hybrid_asgi.py
bash vps/check-private-security.sh
bash vps/check-deployment-readiness.sh
echo "VPS_API_AND_READINESS_BATCH_OK"
echo "This is private staging verification, not production approval."
