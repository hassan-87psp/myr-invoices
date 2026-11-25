#!/usr/bin/env bash
# Install a private persistent preview and daily local encrypted backups.
# No root execution of repository code and no changes to public Nginx/DNS.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
PY="$HOME/myr-venv/bin/python"
for cmd in pg_dump pg_restore gpg curl systemctl loginctl; do command -v "$cmd" >/dev/null; done
test -x "$PY"
bash vps/check-migrated.sh
"$PY" -B vps/backend/native_backup.py
mkdir -p "$HOME/.config/systemd/user"
umask 077
cat > "$HOME/.config/systemd/user/myr-preview.service" <<'UNIT'
[Unit]
Description=MYR Invoice private staging preview
After=network.target
[Service]
Type=simple
WorkingDirectory=%h/myr-invoices
ExecStart=%h/myr-venv/bin/python -B -m uvicorn private_preview:api --app-dir vps/backend --host 127.0.0.1 --port 8765 --no-proxy-headers --no-access-log
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=default.target
UNIT
cat > "$HOME/.config/systemd/user/myr-native-backup.service" <<'UNIT'
[Unit]
Description=MYR Invoice encrypted local database backup
[Service]
Type=oneshot
WorkingDirectory=%h/myr-invoices
ExecStart=%h/myr-venv/bin/python -B vps/backend/native_backup.py
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
UNIT
cat > "$HOME/.config/systemd/user/myr-native-backup.timer" <<'UNIT'
[Unit]
Description=Daily MYR Invoice local encrypted backup
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=300
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user enable myr-preview.service myr-native-backup.timer
systemctl --user restart myr-preview.service
systemctl --user start myr-native-backup.timer
for i in {1..15}; do
  if curl -fsS --max-time 2 http://127.0.0.1:8765/health; then echo; break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8765/health >/dev/null
systemctl --user is-active myr-preview.service myr-native-backup.timer
if [ "$(loginctl show-user "$(id -un)" -p Linger --value)" != yes ]; then
  echo "LINGER_REQUIRED: run sudo loginctl enable-linger myradmin to keep services alive after logout"
  echo "VPS_PRIVATE_SERVICE_STARTED; reboot persistence not yet verified"
else
  echo "VPS_PRIVATE_SERVICE_AND_BACKUP_READY"
fi
echo "Preview still private; original frontend integration, offsite backups, restore drill and public SSL pending."
