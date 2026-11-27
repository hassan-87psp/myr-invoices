#!/usr/bin/env bash
# Disposable cluster only, no sudo, no live DB credentials, no TCP listener.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
PY="$HOME/myr-venv/bin/python"
test -x "$PY"
if ! command -v pg_config >/dev/null; then
    echo "PostgreSQL binaries unavailable; no changes made."
    exit 2
fi
BIN="$(pg_config --bindir)"
for exe in initdb pg_ctl createdb; do
    test -x "$BIN/$exe" || { echo "Required local PostgreSQL binary unavailable: $exe"; exit 2; }
done
if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run this test as root."
    exit 2
fi
ROOT="$(mktemp -d /tmp/myr-lhdn-rehearsal-XXXXXXXX)"
cleanup() {
    if [ -f "$ROOT/data/postmaster.pid" ]; then
        "$BIN/pg_ctl" -D "$ROOT/data" -m immediate -w stop >/dev/null 2>&1 || { echo "Temporary cluster stop failed: $ROOT"; return 1; }
    fi
    rm -rf -- "$ROOT"
}
trap cleanup EXIT
mkdir -m 700 "$ROOT/socket"
# Ignore inherited connection parameters. All commands use the private socket.
unset PGHOST PGHOSTADDR PGPORT PGDATABASE PGUSER PGPASSWORD PGPASSFILE PGSERVICE PGSERVICEFILE PGOPTIONS PGSSLMODE
"$BIN/initdb" -D "$ROOT/data" -U myr_lhdn_test --auth-local=trust --auth-host=reject --encoding=UTF8 --no-locale >"$ROOT/init.log"
"$BIN/pg_ctl" -D "$ROOT/data" -l "$ROOT/postgres.log" -o "-c listen_addresses='' -c unix_socket_directories='$ROOT/socket' -c unix_socket_permissions=0700 -p 55439" -w start >/dev/null
"$BIN/createdb" -h "$ROOT/socket" -p 55439 -U myr_lhdn_test myr_lhdn_rehearsal
env -u MYR_PRODUCTION_RELEASE "$PY" -B vps/backend/check_lhdn_disposable_db.py "$ROOT"
