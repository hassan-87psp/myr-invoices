#!/usr/bin/env bash
# One-time operator installation. The installed worker never executes remote scripts.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
test "$#" -eq 0 || { test "$#" -eq 1 && test "$1" = --recover-billing; }
cd "$HOME/myr-invoices"
CONFIG="$HOME/.config/myrinvoice"
DIR="$CONFIG/frontend-autodeploy"
UNITS="$HOME/.config/systemd/user"
PY="$HOME/myr-venv/bin/python"
PIN=4942c9562c5012c75ab75c10f116fefae039d48a
test "$(cat "$CONFIG/production-writes-enabled")" = "$PIN"
test "$(cat "$CONFIG/native-auth-pilot-enabled")" = "$PIN"
for stem in myr-static-deploy myr-core-backend-deploy myr-core-frontend-deploy; do
    if systemctl --user is-active --quiet "$stem.timer" || systemctl --user is-active --quiet "$stem.service"; then
        echo "Conflicting deploy active: $stem"; exit 1
    fi
done
command -v node >/dev/null
command -v git >/dev/null
"$PY" -B -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' vps/backend/frontend_autodeploy.py
"$PY" -B -m json.tool vps/approved-frontend-releases.json >/dev/null
mkdir -p "$DIR" "$UNITS"
chmod 700 "$DIR"
if test "$(loginctl show-user "$(id -un)" -p Linger --value)" != yes; then
    sudo loginctl enable-linger "$(id -un)"
fi
test "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes
# Stop only this publisher before replacing its locally installed program.
systemctl --user stop myr-frontend-autodeploy.timer myr-frontend-autodeploy.service 2>/dev/null || true
install -m 0600 vps/backend/frontend_autodeploy.py "$DIR/worker.py"
cat > "$UNITS/myr-frontend-autodeploy.service" <<EOF
[Unit]
Description=MYR approved frontend auto-publisher
[Service]
Type=oneshot
WorkingDirectory=$HOME/myr-invoices
ExecStart=$PY -B $DIR/worker.py
NoNewPrivileges=true
PrivateTmp=true
TimeoutStartSec=infinity
UMask=0077
EOF
cat > "$UNITS/myr-frontend-autodeploy.timer" <<'EOF'
[Unit]
Description=Check approved MYR frontend releases
[Timer]
OnBootSec=10s
OnUnitInactiveSec=20s
AccuracySec=1s
Unit=myr-frontend-autodeploy.service
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now myr-frontend-autodeploy.timer
echo MYR_FRONTEND_AUTO_TIMER_ENABLED
if test "${1:-}" = --recover-billing; then
    if ! systemctl --user is-active --quiet myr-billing-readonly.service; then
        # Explicit one-time recovery under the operator's sudo session, never from timer.
        "$PY" -B vps/backend/publish_billing_readonly.py --publish-readonly-billing || {
            echo MYR_AUTO_ENABLED_BUT_WAITING_FOR_BILLING_RECOVERY
            exit 1
        }
    fi
fi
systemctl --user start myr-frontend-autodeploy.service
systemctl --user is-active --quiet myr-frontend-autodeploy.timer
journalctl --user -u myr-frontend-autodeploy.service -n 12 --no-pager
echo MYR_FRONTEND_AUTODEPLOY_INSTALLED
