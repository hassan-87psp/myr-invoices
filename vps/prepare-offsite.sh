#!/usr/bin/env bash
# Prepare a fresh encrypted archive and checksum for an independent offsite copy.
# Does not transmit any data or key.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
"$HOME/myr-venv/bin/python" -B vps/backend/native_backup.py
folder="$HOME/myr-private-backups/native"
cd "$folder"
latest="$(find . -maxdepth 1 -type f -name 'native-*.dump.gpg' -printf '%f\n' | sort | tail -n1)"
test -n "$latest"
sha256sum "$latest" > "$latest.sha256"
sha256sum -c "$latest.sha256"
echo "VPS_OFFSITE_EXPORT_PREPARED"
echo "Encrypted archive: $folder/$latest"
echo "Checksum: $folder/$latest.sha256"
echo "Copy both to independent storage; escrow the decryption key separately in a secure password manager."
echo "Do not paste the key into chat, upload it beside the backup, or commit it to GitHub."
echo "Offsite transfer and independent restore have NOT been verified."
