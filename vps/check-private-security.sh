#!/usr/bin/env bash
# Private staging security checks. No firewall, DNS or production changes.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
PY="$HOME/myr-venv/bin/python"
systemctl --user is-active --quiet myr-preview.service
systemctl --user is-active --quiet myr-native-backup.timer
test "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes
ss -H -ltn | "$PY" -B -c '
import sys
ports={5432:[],8765:[]}
for line in sys.stdin:
    fields=line.split()
    if len(fields)<4: continue
    host,sep,port=fields[3].rpartition(":")
    if sep and port.isdigit() and int(port) in ports: ports[int(port)].append(host)
for p,hosts in ports.items():
    if not hosts or any(h not in ("127.0.0.1","[::1]","::1") for h in hosts):
        raise SystemExit("CHECK FAILED: port %s must listen only on loopback"%p)
print("VPS_DATABASE_AND_API_LOOPBACK_OK")
'
"$PY" -B - <<'PYCODE'
import sys
from pathlib import Path
sys.path.insert(0,"vps/backend")
from app import connect
cfg=Path.home()/".config/myrinvoice"
for name in ("db-password","native-backup-key","hybrid-read-user","hybrid-write-test-company"):
    p=cfg/name
    if not p.is_file() or p.is_symlink() or p.stat().st_mode & 0o077:
        raise SystemExit("Unsafe or missing private file: "+name)
with connect() as conn:
    row=conn.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()").fetchone()
    assert row and row[0], "Database connection must use TLS"
    row=conn.execute("SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    assert row and not any(row),"Database application role has excessive privileges"
    assert conn.execute("SELECT count(*) FROM myr_native.companies WHERE data->>'vpsSyntheticWriteTest'='true'").fetchone()[0]>=1
print("VPS_PRIVATE_SECRETS_AND_DATABASE_ROLE_OK")
PYCODE
curl -fsS --max-time 5 http://127.0.0.1:8765/health >/dev/null
echo "VPS_PRIVATE_SECURITY_CHECK_OK"
