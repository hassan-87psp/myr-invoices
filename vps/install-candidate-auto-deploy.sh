#!/usr/bin/env bash
# Automatic private candidate releases only. Never changes Nginx or production DB.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
REPO="$HOME/myr-invoices"
BASE="$HOME/myr-backend-releases"
PY="$HOME/myr-venv/bin/python"
UNITS="$HOME/.config/systemd/user"
BIN="$HOME/.local/bin/myr-candidate-deploy"
DROP="$UNITS/myr-business-api.service.d/20-candidate-release.conf"
mkdir -p "$BASE/releases" "$(dirname "$BIN")" "$(dirname "$DROP")"
health() {
    local url=http://127.0.0.1:8766 i
    for i in {1..15}; do
        if curl -fsS --max-time 2 "$url/health" 2>/dev/null | "$PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"] is False' 2>/dev/null; then
            break
        fi
        sleep 1
    done
    curl -fsS --max-time 5 "$url/health" | "$PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"] is False' &&
    curl -fsS --max-time 10 "$url/candidate/" | grep -F 'PRIVATE VPS DATABASE CANDIDATE' >/dev/null &&
    test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$url/workspace")" = 401 &&
    test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"p_token":"00000000000000000000000000000000"}' "$url/links/read")" = 503
}
switch_link() {
    ln -s "$1" "$BASE/.current.$$"
    mv -Tf "$BASE/.current.$$" "$BASE/current"
}
deploy() {
    exec 9>"$BASE/deploy.lock"
    flock -n 9 || exit 0
    export GIT_TERMINAL_PROMPT=0
    export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15'
    git -C "$REPO" fetch --quiet --no-tags origin refs/heads/main:refs/remotes/origin/main
    commit="$(git -C "$REPO" rev-parse --verify refs/remotes/origin/main^{commit})"
    release="$BASE/releases/$commit"
    previous="$(readlink "$BASE/current" || true)"
    if [ "$previous" = "$release" ] && [ -f "$DROP" ]; then
        echo "MYR_CANDIDATE_UP_TO_DATE $commit"
        return
    fi
    stage="$(mktemp -d "$BASE/releases/.build.XXXXXXXX")"
    trap 'rm -rf -- "$stage"; rm -f -- "$BASE/.current.$$"' EXIT
    git -C "$REPO" archive "$commit" vps/backend config.js | tar -xf - -C "$stage"
    test -z "$(find "$stage" -type l -print -quit)"
    export MYR_CANDIDATE_DIR="$stage/candidate"
    "$PY" -B "$stage/vps/backend/build_business_candidate.py"
    "$PY" -B - "$stage/candidate/index.html" <<'PYCODE'
import re,sys,subprocess
from pathlib import Path
for attrs,code in re.findall(r'<script([^>]*)>(.*?)</script>',Path(sys.argv[1]).read_text(),re.S|re.I):
    if code.strip() and 'application/ld+json' not in attrs and 'application/json' not in attrs:
        subprocess.run(["node","--check","-"],input=code,text=True,check=True)
PYCODE
    for testfile in check_business_asgi.py business_admin.py business_links.py business_api.py; do
        "$PY" -B "$stage/vps/backend/$testfile"
    done
    unset MYR_CANDIDATE_DIR
    if [ ! -e "$release" ]; then
        mv "$stage" "$release"
    else
        diff -qr "$stage" "$release" >/dev/null
    fi
    had_drop=0
    if [ -f "$DROP" ]; then
        had_drop=1
        cp "$DROP" "$BASE/previous-dropin"
    fi
    cat >"$DROP" <<'UNIT'
[Service]
WorkingDirectory=%h/myr-backend-releases/current/vps/backend
Environment=MYR_CANDIDATE_DIR=%h/myr-backend-releases/current/candidate
UNIT
    switch_link "$release"
    if systemctl --user daemon-reload && systemctl --user restart myr-business-api.service && health; then
        echo "MYR_CANDIDATE_RELEASE_DEPLOYED $commit"
    else
        if [ -n "$previous" ]; then switch_link "$previous"; else rm -f "$BASE/current"; fi
        if [ "$had_drop" = 1 ]; then cp "$BASE/previous-dropin" "$DROP"; else rm -f "$DROP"; fi
        systemctl --user daemon-reload
        systemctl --user restart myr-business-api.service
        health
        echo "Candidate release failed; previous service restored." >&2
        return 1
    fi
}
if [ "${1:-}" = --run ]; then
    deploy
    exit 0
fi
# The timer executes code from the trusted private main branch as myradmin,
# never root. Enable only on this isolated candidate service.
test -d "$REPO/.git"
test -f "$UNITS/myr-business-api.service"
systemctl --user is-active --quiet myr-business-api.service
install -m 0700 "$0" "$BIN"
cat >"$UNITS/myr-candidate-deploy.service" <<'UNIT'
[Unit]
Description=MYR Invoice private candidate GitHub release
[Service]
Type=oneshot
ExecStart=%h/.local/bin/myr-candidate-deploy --run
TimeoutStartSec=300
NoNewPrivileges=yes
UMask=0077
UNIT
cat >"$UNITS/myr-candidate-deploy.timer" <<'UNIT'
[Unit]
Description=Check MYR private candidate for GitHub changes
[Timer]
OnCalendar=*:0/5
Persistent=true
Unit=myr-candidate-deploy.service
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user start myr-candidate-deploy.service
systemctl --user enable --now myr-candidate-deploy.timer
systemctl --user list-timers myr-candidate-deploy.timer --no-pager
echo "MYR_PRIVATE_BACKEND_AUTO_DEPLOY_READY"
echo "Candidate only. Production writes remain disabled; no public API proxy or database cutover."
