#!/usr/bin/env bash
# Create a separate private, stopped Sandbox cluster. No sudo, public port,
# production connection, provider requests, secrets, or real company imports.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
test "$(id -u)" -ne 0 || { echo "Run as a non-root operator"; exit 2; }
MODE="${1:---install}"
case "$MODE" in --install|--rehearse) ;; *) echo "Usage: $0 [--install|--rehearse]"; exit 2;; esac
test "$#" -le 1
BIN="$(pg_config --bindir)"
for exe in initdb pg_ctl psql createdb pg_dump pg_restore; do test -x "$BIN/$exe"; done
PY="${MYR_SANDBOX_TEST_PYTHON:-$HOME/myr-venv/bin/python}"
if [ "$MODE" = --rehearse ]; then test -x "$PY"; "$PY" -c 'import psycopg'; fi
unset PGHOST PGHOSTADDR PGPORT PGDATABASE PGUSER PGPASSWORD PGPASSFILE PGSERVICE PGSERVICEFILE PGOPTIONS PGSSLMODE MYR_PRODUCTION_RELEASE
# Only a private directory owned by the current operator is used.
if [ "$MODE" = --rehearse ]; then
 ROOT="$(mktemp -d /tmp/myr-lhdn-isolated-XXXXXXXX)"
else
 ROOT="$HOME/.local/share/myrinvoice/lhdn-sandbox"
 mkdir -p "$HOME/.local/share/myrinvoice"
 test ! -L "$HOME/.local/share/myrinvoice"
 if ! mkdir -m 700 "$ROOT"; then
  echo "Sandbox directory already exists. Refusing to modify it. Use --rehearse for fresh disposable tests."
  exit 2
 fi
fi
[[ "$ROOT" =~ ^[A-Za-z0-9_./-]+$ ]] || { echo "Unsafe private path"; exit 2; }
test "$(stat -c %u "$ROOT")" = "$(id -u)" && test "$(stat -c %a "$ROOT")" = 700
started=0
cleanup(){
 if [ "$started" -eq 1 ]; then
  "$BIN/pg_ctl" -D "$ROOT/data" -m fast -w stop >/dev/null || { echo "Private cluster stop failed; no deletion performed"; return 1; }
 fi
 if [ "$MODE" = --rehearse ]; then rm -rf -- "$ROOT"; fi
}
trap cleanup EXIT
mkdir -m 700 "$ROOT/socket"
"$BIN/initdb" -D "$ROOT/data" -U myr_lhdn_sandbox_admin --auth-local=trust --auth-host=reject --encoding=UTF8 --no-locale >"$ROOT/init.log"
# Socket is under a 0700 parent. No TCP listener and no connection to native VPS DB.
cat >> "$ROOT/data/postgresql.conf" <<EOF
listen_addresses = ''
unix_socket_directories = '$ROOT/socket'
unix_socket_permissions = 0700
port = 55441
EOF
"$BIN/pg_ctl" -D "$ROOT/data" -l "$ROOT/postgres.log" -w start >/dev/null
started=1
PSQL=("$BIN/psql" -X -v ON_ERROR_STOP=1 -h "$ROOT/socket" -p 55441 -U myr_lhdn_sandbox_admin)
"${PSQL[@]}" -d postgres -q <<'SQL'
CREATE ROLE myr_lhdn_sandbox_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
CREATE DATABASE myr_lhdn_sandbox;
REVOKE ALL ON DATABASE myr_lhdn_sandbox FROM PUBLIC;
GRANT CONNECT ON DATABASE myr_lhdn_sandbox TO myr_lhdn_sandbox_worker;
SQL
for sql in lhdn-isolated-base.review.sql lhdn-submission-intents.review.sql lhdn-sandbox-poll.review.sql lhdn-isolated-worker.review.sql; do
 "${PSQL[@]}" -d myr_lhdn_sandbox -q -f "vps/$sql"
done
if [ "$MODE" = --rehearse ]; then
 "$PY" -B vps/backend/check_lhdn_isolated_worker.py "$ROOT"
 # Rehearse a full logical backup and restoration into a second private database.
 "$BIN/pg_dump" -h "$ROOT/socket" -p 55441 -U myr_lhdn_sandbox_admin -Fc -f "$ROOT/synthetic.dump" myr_lhdn_sandbox
 "$BIN/createdb" -h "$ROOT/socket" -p 55441 -U myr_lhdn_sandbox_admin myr_lhdn_restore_check
 "$BIN/pg_restore" -h "$ROOT/socket" -p 55441 -U myr_lhdn_sandbox_admin --exit-on-error -d myr_lhdn_restore_check "$ROOT/synthetic.dump"
 before="$("${PSQL[@]}" -d myr_lhdn_sandbox -Atc "SELECT count(*)||':'||count(*) FILTER (WHERE state='valid') FROM myr_native.lhdn_submission_intents")"
 after="$("${PSQL[@]}" -d myr_lhdn_restore_check -Atc "SELECT count(*)||':'||count(*) FILTER (WHERE state='valid') FROM myr_native.lhdn_submission_intents")"
 test "$before" = "$after"
 echo "MYR_SANDBOX_SYNTHETIC_RESTORE_OK"
 echo "MYR_SANDBOX_ISOLATED_REHEARSAL_OK"
else
 # An empty, stopped cluster only. No worker or public API is installed.
 test "$("${PSQL[@]}" -d myr_lhdn_sandbox -Atc 'SELECT count(*) FROM myr_native.companies')" = 0
 echo "MYR_EMPTY_SANDBOX_DATABASE_INSTALLED"
fi
