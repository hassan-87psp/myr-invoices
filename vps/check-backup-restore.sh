#!/usr/bin/env bash
# Restore a real encrypted backup into a disposable, Unix-socket-only cluster.
# No production DB writes, public deployment, or secret output.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
systemctl --user is-active --quiet myr-preview.service
systemctl --user is-active --quiet myr-native-backup.timer
test "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes
"$HOME/myr-venv/bin/python" -B vps/backend/native_backup.py
backup_dir="$HOME/myr-private-backups/native"
backup="$(find "$backup_dir" -maxdepth 1 -type f -name 'native-*.dump.gpg' -printf '%f\n' | sort | tail -n1)"
test -n "$backup"
key="$HOME/.config/myrinvoice/native-backup-key"
test -f "$key" && test ! -L "$key"
bin="$(pg_config --bindir)"
if [ ! -x "$bin/initdb" ]; then
  bin="$(find /usr/lib/postgresql -mindepth 2 -maxdepth 2 -type d -name bin | sort -V | tail -n1)"
fi
for cmd in initdb pg_ctl createdb pg_restore psql; do test -x "$bin/$cmd"; done
# Short private path avoids Unix socket path length limits.
tmp="$(mktemp -d /tmp/myr-restore.XXXXXXXX)"
cleanup() {
  if [ -f "$tmp/data/postmaster.pid" ]; then
    "$bin/pg_ctl" -D "$tmp/data" -m fast -w stop >/dev/null || {
      echo "Temporary restore cluster could not stop; retained at $tmp" >&2
      return 1
    }
  fi
  rm -rf -- "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
gpg --batch --yes --no-symkey-cache --pinentry-mode loopback --passphrase-file "$key" --output "$tmp/db.dump" --decrypt "$backup_dir/$backup"
"$bin/pg_restore" --list "$tmp/db.dump" >/dev/null
unset PGHOST PGHOSTADDR PGPORT PGDATABASE PGUSER PGPASSWORD PGPASSFILE PGSERVICE PGSERVICEFILE PGOPTIONS PGSSLMODE PGCONNECT_TIMEOUT
"$bin/initdb" -D "$tmp/data" -U myradmin --auth-local=trust --auth-host=reject --no-instructions >"$tmp/init.log" 2>&1
mkdir "$tmp/socket"
"$bin/pg_ctl" -D "$tmp/data" -l "$tmp/pg.log" -o "-c listen_addresses='' -c unix_socket_directories=$tmp/socket -c unix_socket_permissions=0700 -p 55439" -w start >/dev/null
args=(-h "$tmp/socket" -p 55439 -U myradmin)
"$bin/createdb" "${args[@]}" myr_restore_drill
"$bin/pg_restore" "${args[@]}" -d myr_restore_drill --exit-on-error --single-transaction --no-owner --no-privileges "$tmp/db.dump" >"$tmp/restore.log" 2>&1 || {
  echo "Restore failed; no live database modified. Check archive compatibility." >&2
  exit 1
}
count="$("$bin/psql" -X "${args[@]}" -d myr_restore_drill -Atq -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='myr_native' AND table_type='BASE TABLE'")"
test "$count" -ge 10
"$bin/psql" -X "${args[@]}" -d myr_restore_drill -Atq -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM myr_native.users; SELECT count(*) FROM myr_native.companies; SELECT count(*) FROM myr_native.company_members; SELECT count(*) FROM myr_native.lhdn_documents;" >/dev/null
echo "VPS_ISOLATED_BACKUP_RESTORE_OK"
curl -fsS --max-time 5 http://127.0.0.1:8765/health
echo
test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/hybrid/workspace)" = 401
echo "VPS_PRIVATE_FOUNDATION_CHECK_OK"
echo "Still pending: browser sign-in, native write integration, independent offsite backup, public HTTPS and cutover."
