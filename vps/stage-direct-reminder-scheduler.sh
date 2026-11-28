#!/usr/bin/env bash
# Prepare a pinned reminder scheduler, without enabling or starting it.
# Only an independently reviewed Sandbox release may activate it.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
test "$#" = 1 && test "$1" = --stage-disabled
cd "$HOME/myr-invoices"
PIN=4942c9562c5012c75ab75c10f116fefae039d48a
REF=d54b3b5bb9806ceb385f6ff36d6dd45521648862
CORE="$HOME/myr-backend-releases/production/$PIN/vps/backend"
RELEASE="$HOME/myr-backend-releases/direct-erp-reminder/$REF"
UNITS="$HOME/.config/systemd/user"
SERVICE=myr-direct-expiry-reminder.service
TIMER=myr-direct-expiry-reminder.timer
PY="$HOME/myr-venv/bin/python"
test -d "$CORE" && test -x "$PY"
test "$(cat "$HOME/.config/myrinvoice/production-writes-enabled")" = "$PIN"
for p in "$RELEASE" "$UNITS/$SERVICE" "$UNITS/$TIMER"; do
    test ! -e "$p" && test ! -L "$p"
done
for unit in "$SERVICE" "$TIMER"; do
    test "$(systemctl --user show "$unit" -p LoadState --value)" = not-found
done
test ! -e "$HOME/.config/myrinvoice/direct-erp-reminder-optin.json"
tmp=$(mktemp -d)
installed=0
success=0
cleanup(){
    rc=$?
    trap - EXIT
    if [ "$installed" = 1 ] && [ "$success" = 0 ]; then
        rm -f "$UNITS/$SERVICE" "$UNITS/$TIMER"
        rm -rf "$RELEASE"
        systemctl --user daemon-reload || true
    fi
    rm -rf "$tmp"
    exit "$rc"
}
trap cleanup EXIT
for name in lhdn_direct_expiry_reminder_candidate.py lhdn_direct_reminder_outbox_candidate.py lhdn_direct_reminder_job_candidate.py lhdn_direct_reminder_runtime_candidate.py lhdn_direct_vault_candidate.py lhdn_direct_candidate.py lhdn_protocol_candidate.py; do
    git show "$REF:vps/backend/$name" > "$tmp/$name"
done
PYTHONPATH="$tmp:$CORE" "$PY" -B "$tmp/lhdn_direct_reminder_runtime_candidate.py" --test
PYTHONPATH="$tmp:$CORE" "$PY" -B "$tmp/lhdn_direct_reminder_job_candidate.py"
test "$(PYTHONPATH="$tmp:$CORE" "$PY" -B "$tmp/lhdn_direct_reminder_runtime_candidate.py")" = MYR_DIRECT_REMINDER_DISABLED
mkdir -p "$UNITS" "$(dirname "$RELEASE")"
installed=1
mkdir "$RELEASE"
install -m 0600 "$tmp/"*.py "$RELEASE/"
cat > "$UNITS/$SERVICE" <<UNIT
[Unit]
Description=MYR Direct ERP Sandbox expiry reminders (disabled staging)
ConditionPathExists=%h/.config/myrinvoice/direct-erp-reminder-optin.json
[Service]
Type=oneshot
WorkingDirectory=$RELEASE
Environment=PYTHONPATH=$RELEASE:$CORE
Environment=MYR_PRODUCTION_RELEASE=$PIN
ExecStart=$PY -B $RELEASE/lhdn_direct_reminder_runtime_candidate.py --run-approved-sandbox
TimeoutStartSec=120
NoNewPrivileges=yes
UMask=0077
UNIT
cat > "$UNITS/$TIMER" <<UNIT
[Unit]
Description=Daily MYR Direct ERP Sandbox reminder (disabled staging)
[Timer]
OnCalendar=*-*-* 09:00:00 Asia/Kuala_Lumpur
Persistent=true
Unit=$SERVICE
[Install]
WantedBy=timers.target
UNIT
systemd-analyze calendar '*-*-* 09:00:00 Asia/Kuala_Lumpur' >/dev/null
systemctl --user daemon-reload
test "$(systemctl --user is-enabled "$TIMER" 2>/dev/null || true)" = disabled
! systemctl --user is-active --quiet "$TIMER"
success=1
echo MYR_DIRECT_REMINDER_SCHEDULER_STAGED_DISABLED
echo "No email sent. No timer started. Explicit owner opt-in and separate mail release required."
