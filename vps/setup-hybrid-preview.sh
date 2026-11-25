#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
PY="$HOME/myr-venv/bin/python"
systemctl --user is-active --quiet myr-preview.service
"$PY" -B vps/backend/build_hybrid_preview.py
"$PY" -B - <<'PYCODE'
import sys
from uuid import UUID
sys.path.insert(0,"vps/backend")
from hybrid_workspace import workspace,GRANT
from fastapi import HTTPException
from app import connect
with connect() as conn:
    try:
        workspace(conn,UUID(int=0),"unauthorized@example.invalid")
    except HTTPException as e:
        assert e.status_code==403
    else:
        raise SystemExit("Unauthorized workspace unexpectedly accessible")
    if GRANT.is_file():
        uid=UUID(GRANT.read_text().strip())
        row=conn.execute("SELECT email FROM myr_native.users WHERE id=%s",(uid,)).fetchone()
        assert row
        result=workspace(conn,uid,row[0])
        assert result["mode"]=="read_only"
        assert result["companies"]
        assert all(x["role"]=="Read-Only" for x in result["members"])
        assert not result["profile"]["is_platform_admin"]
        print("VPS_IMPORTED_WORKSPACE_READ_OK")
    conn.rollback()
print("VPS_WORKSPACE_AUTHORIZATION_CHECK_OK")
PYCODE
systemctl --user restart myr-preview.service
for i in {1..15}; do
    if curl -fsS --max-time 2 http://127.0.0.1:8765/health >/dev/null 2>&1; then break; fi
    sleep 1
done
curl -fsS http://127.0.0.1:8765/health
echo
curl -fsS http://127.0.0.1:8765/website/ | grep -Fq 'PRIVATE VPS PREVIEW' || {
    # grep -q may close a large HTML stream early; verify via a temporary file instead.
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    curl -fsS http://127.0.0.1:8765/website/ -o "$tmp"
    grep -Fq 'PRIVATE VPS PREVIEW' "$tmp"
}
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/hybrid/workspace)" = 401
echo "VPS_HYBRID_READ_ONLY_READY"
echo "Original website preview: /website/ ; native admin preview: /"
echo "Supabase login with the approved existing owner needs real browser testing. Writes, email and LHDN submissions disabled in preview."
