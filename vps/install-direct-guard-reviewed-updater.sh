#!/usr/bin/env bash
# Install a user timer for the reviewed guard-only updater. No sudo.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
test "$#" = 1 && test "$1" = --install-guard-timer
cd "$HOME/myr-invoices"
REF=c6a1ceaaf2ab8c4795557eaf30f1ae2f64d14ca4
PY="$HOME/myr-venv/bin/python"
BIN="$HOME/.local/bin/myr-direct-guard-reviewed-updater.py"
UNITS="$HOME/.config/systemd/user"
SERVICE=myr-direct-guard-reviewed-update.service
TIMER=myr-direct-guard-reviewed-update.timer
APPROVAL="$HOME/.config/myrinvoice/direct-erp-guard-approved-commit"
test ! -e "$APPROVAL" && test ! -L "$APPROVAL"
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
git show "$REF:vps/backend/direct_guard_reviewed_updater.py" > "$tmp/updater.py"
"$PY" -B "$tmp/updater.py" --rehearse
mkdir -p "$HOME/.local/bin" "$UNITS"
installed=1
install -m 0700 "$tmp/updater.py" "$BIN"
cat > "$UNITS/$SERVICE" <<'UNIT'
[Unit]
Description=MYR Direct ERP guard-only reviewed release check
[Service]
Type=oneshot
ExecStart=%h/myr-venv/bin/python -B %h/.local/bin/myr-direct-guard-reviewed-updater.py --run
TimeoutStartSec=600
NoNewPrivileges=yes
UMask=0077
UNIT
cat > "$UNITS/$TIMER" <<'UNIT'
[Unit]
Description=Check locally approved MYR Direct ERP guard release every five minutes
[Timer]
OnCalendar=*-*-* *:0/5:00
Persistent=true
Unit=myr-direct-guard-reviewed-update.service
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user start "$SERVICE"
systemctl --user enable --now "$TIMER"
systemctl --user is-active --quiet "$TIMER"
systemctl --user is-active --quiet myr-direct-erp-guard.service
success=1
echo MYR_DIRECT_REVIEWED_UPDATE_TIMER_ACTIVE
echo "No release approved; no deployment. Future updates require a locally approved exact commit already fetched into Git."
