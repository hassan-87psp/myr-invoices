#!/usr/bin/env bash
# Restore the latest verified encrypted archive into a temporary, private local cluster.
# No live database connection, no production restart, no customer record output.
set -euo pipefail
umask 077
test "$(id -u)" -ne 0
test "$(id -un)" = myradmin
BIN="$(pg_config --bindir)"
for exe in initdb pg_ctl createdb pg_restore psql; do
    test -x "$BIN/$exe"
done
BASE="$HOME/myr-private-backups/native"
KEY="$HOME/.config/myrinvoice/native-backup-key"
PY="$HOME/myr-venv/bin/python"
test -x "$PY"
ARCHIVE="$("$PY" - "$BASE" "$KEY" <<'PY'
import hashlib, os, sys, stat
from pathlib import Path
base,key=map(Path,sys.argv[1:])
def private(p):
    s=p.lstat()
    return stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and not s.st_mode&0o077
if not private(key):raise SystemExit("Unsafe backup key")
files=sorted((p for p in base.glob("native-*.dump.gpg") if private(p)),key=lambda p:p.stat().st_mtime,reverse=True)
if not files:raise SystemExit("No private encrypted backup")
p=files[0]; checksum=p.with_name(p.name+".sha256")
if not private(checksum):raise SystemExit("Unsafe checksum file")
with p.open("rb") as f: digest=hashlib.file_digest(f,"sha256").hexdigest()
if checksum.read_text().strip()!=digest+"  "+p.name:raise SystemExit("Backup checksum mismatch")
print(p)
PY
)"
# Conservative free-space gate; archive is compressed and encrypted.
FREE="$(df -Pk "$HOME" | awk 'END {print $4}')"
SIZE="$(stat -c %s "$ARCHIVE")"
test "$FREE" -ge "$((1048576 + SIZE / 1024 * 12))" || { echo "Insufficient free space for isolated restore"; exit 2; }
ROOT="$(mktemp -d "$HOME/.myr-restore-rehearsal-XXXXXXXX")"
cleanup() {
    if [ -f "$ROOT/data/postmaster.pid" ]; then
        "$BIN/pg_ctl" -D "$ROOT/data" -m immediate -w stop >/dev/null 2>&1 || { echo "Temporary cluster stop failed; private directory retained: $ROOT"; return 1; }
    fi
    rm -rf -- "$ROOT"
}
trap cleanup EXIT
mkdir -m 700 "$ROOT/socket"
unset PGHOST PGHOSTADDR PGPORT PGDATABASE PGUSER PGPASSWORD PGPASSFILE PGSERVICE PGSERVICEFILE PGOPTIONS PGSSLMODE
echo "=== Encrypted backup verification ==="
gpg --batch --no-symkey-cache --pinentry-mode loopback --passphrase-file "$KEY" --decrypt --output "$ROOT/restore.dump" "$ARCHIVE" 2>"$ROOT/gpg.log" || { echo "Backup decryption failed"; exit 1; }
"$BIN/pg_restore" --list "$ROOT/restore.dump" >"$ROOT/archive.list"
echo "=== Isolated PostgreSQL restore ==="
"$BIN/initdb" -D "$ROOT/data" -U myr_restore_test --auth-local=trust --auth-host=reject --encoding=UTF8 --no-locale >"$ROOT/init.log" 2>&1
"$BIN/pg_ctl" -D "$ROOT/data" -l "$ROOT/postgres.log" -o "-c listen_addresses='' -c unix_socket_directories='$ROOT/socket' -c unix_socket_permissions=0700 -p 55440 -c max_connections=10" -w start >/dev/null
"$BIN/createdb" -h "$ROOT/socket" -p 55440 -U myr_restore_test myr_restore_rehearsal
export PGHOST="$ROOT/socket" PGPORT=55440 PGUSER=myr_restore_test PGDATABASE=myr_restore_rehearsal
IDENTITY="$("$BIN/psql" -XAt -v ON_ERROR_STOP=1 -c "SELECT current_database()||'|'||current_user||'|'||(inet_server_addr() IS NULL)::text")"
test "$IDENTITY" = "myr_restore_rehearsal|myr_restore_test|true"
"$BIN/pg_restore" --exit-on-error --no-owner --no-privileges --no-tablespaces --dbname=myr_restore_rehearsal "$ROOT/restore.dump" >"$ROOT/restore.log" 2>&1 || { echo "Isolated restore failed; no production changes. Review schema/role dependencies before retry."; exit 1; }
TABLES="$("$BIN/psql" -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_tables WHERE schemaname='myr_native'")"
test "$TABLES" -ge 11
"$BIN/psql" -XAt -v ON_ERROR_STOP=1 -c "BEGIN READ ONLY; SELECT count(*) FROM myr_native.users; SELECT count(*) FROM myr_native.companies; SELECT count(*) FROM myr_native.lhdn_documents; ROLLBACK;" >"$ROOT/counts.log"
if [ "${1:-}" = "--billing-rehearsal" ]; then
    cd "$(dirname "$0")/.."
    "$PY" -B vps/backend/check_billing_restored_schema.py "$ROOT" >"$ROOT/billing.log" 2>&1 || { echo "Billing restored schema rehearsal failed; no production changes."; exit 1; }
    grep -Fx "MYR_BILLING_RESTORED_SCHEMA_AND_RESTRICTED_ROLE_OK" "$ROOT/billing.log"
fi
echo "Native tables restored: $TABLES"
echo "MYR_ENCRYPTED_BACKUP_RESTORE_OK"
echo "Local restore verified. Offsite recovery and original production ownership/ACL restoration remain unverified."
