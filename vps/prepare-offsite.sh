#!/usr/bin/env bash
# Prepare a fresh encrypted archive and checksum for an independent offsite copy.
# Does not transmit any data or key.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
"$HOME/myr-venv/bin/python" -B vps/backend/native_backup.py
folder="$HOME/myr-private-backups/native"
# Verify the original backup checksum; never bless changed bytes by rewriting it.
latest="$("$HOME/myr-venv/bin/python" -B - "$folder" <<'PY'
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"vps/backend"))
from check_private_reliability import inspect_backups
result=inspect_backups(Path(sys.argv[1]),time.time(),include_name=True)
if result["status"]!="verified_checksum":
    raise SystemExit("Offsite export refused: "+result["status"])
print(result["archive_name"])
PY
)"
echo "VPS_OFFSITE_EXPORT_PREPARED"
echo "Encrypted archive: $folder/$latest"
echo "Checksum: $folder/$latest.sha256"
echo "Copy both to independent storage; escrow the decryption key separately in a secure password manager."
echo "Do not paste the key into chat, upload it beside the backup, or commit it to GitHub."
echo "Offsite transfer and independent restore have NOT been verified."
