#!/usr/bin/env bash
# Local encrypted vault snapshots only. No sudo or production database changes.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
test "$#" = 1 && test "$1" = --install-local-backup
cd "$HOME/myr-invoices"
REF=c13038c04666048078c0a9194b2f5892ff1203f9
PY="$HOME/myr-venv/bin/python"
BIN="$HOME/.local/bin/myr-direct-vault-backup.py"
UNITS="$HOME/.config/systemd/user"
SERVICE=myr-direct-vault-backup.service
TIMER=myr-direct-vault-backup.timer
for file in "$BIN" "$UNITS/$SERVICE" "$UNITS/$TIMER"; do
    test ! -e "$file" && test ! -L "$file"
done
for unit in "$SERVICE" "$TIMER"; do
    test "$(systemctl --user show "$unit" -p LoadState --value)" = not-found
done
tmp=$(mktemp -d)
installed=0
success=0
cleanup() {
    rc=$?
    trap - EXIT
    if [ "$installed" = 1 ] && [ "$success" = 0 ]; then
        systemctl --user disable --now "$TIMER" 2>/dev/null || true
        systemctl --user stop "$SERVICE" 2>/dev/null || true
        rm -f "$BIN" "$UNITS/$SERVICE" "$UNITS/$TIMER"
        systemctl --user daemon-reload || true
    fi
    rm -rf "$tmp"
    exit "$rc"
}
trap cleanup EXIT
git show "$REF:vps/backend/direct_vault_backup_candidate.py" > "$tmp/backup.py"
PYTHONPATH="$HOME/myr-invoices/vps/backend" "$PY" -B "$tmp/backup.py" --rehearse
mkdir -p "$HOME/.local/bin" "$UNITS"
installed=1
install -m 0700 "$tmp/backup.py" "$BIN"
cat > "$UNITS/$SERVICE" <<'UNIT'
[Unit]
Description=MYR Direct ERP local encrypted vault snapshot
[Service]
Type=oneshot
ExecStart=%h/myr-venv/bin/python -B %h/.local/bin/myr-direct-vault-backup.py --backup
TimeoutStartSec=120
NoNewPrivileges=yes
UMask=0077
UNIT
cat > "$UNITS/$TIMER" <<'UNIT'
[Unit]
Description=Daily MYR Direct ERP local vault backup
[Timer]
OnCalendar=daily
Persistent=true
Unit=myr-direct-vault-backup.service
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user start "$SERVICE"
systemctl --user enable --now "$TIMER"
systemctl --user is-active --quiet "$TIMER"
success=1
echo MYR_DIRECT_LOCAL_VAULT_BACKUP_TIMER_ACTIVE
echo "Local ciphertext snapshots only. Offsite copies, retention review and independent restore remain pending."
