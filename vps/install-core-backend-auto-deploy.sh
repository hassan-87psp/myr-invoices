#!/usr/bin/env bash
# Approved production backend + matching frontend; no schema migrations.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
# This legacy publisher predates native auth and the installed manifest worker.
# Refuse before any deployment or service changes, including --run.
for marker in "$HOME/.config/myrinvoice/native-auth-pilot-enabled" "$HOME/.config/myrinvoice/frontend-autodeploy/worker.py"; do
    if [ -e "$marker" ] || [ -L "$marker" ]; then
        echo "MYR_LEGACY_BACKEND_DEPLOY_BLOCKED: native production publisher requires a separate reviewed release mechanism." >&2
        exit 78
    fi
done
REPO="$HOME/myr-invoices"
BASE=/var/www/myrinvoice.com/auto
MARKER="$HOME/.config/myrinvoice/production-writes-enabled"
PY="$HOME/myr-venv/bin/python"
BIN="$HOME/.local/bin/myr-core-backend-deploy"
UNITS="$HOME/.config/systemd/user"
ASSETS=(index.html config.js concurrency.js klcc-skyline.webp myr-auth-night.svg manifest.webmanifest pwa-icon-192.png pwa-icon-512.png robots.txt seo.css sitemap.xml sw.js e-invoice-malaysia/index.html invoice-app-malaysia/index.html invoice-generator-malaysia/index.html invoice-software-malaysia/index.html invoicing-software-for-small-business-malaysia/index.html myinvois-checklist/index.html)
https() {
    curl --noproxy '*' --resolve myrinvoice.com:443:127.0.0.1 --max-time 15 "$@"
}
health() {
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8767/health | "$PY" -c 'import sys,json; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"] is True' &&
    test "$(https -sS -o /dev/null -w '%{http_code}' https://myrinvoice.com/api/myr/workspace)" = 401 &&
    test "$(https -sS -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"p_token":"00000000000000000000000000000000"}' https://myrinvoice.com/api/myr/links/read)" = 404 &&
    test "$(https -sS -o /dev/null -w '%{http_code}' https://myrinvoice.com/api/myr/native/auth/preview)" = 404
}
publish_link() {
    ln -s "$1" "$BASE/.core-frontend.$$"
    mv -Tf "$BASE/.core-frontend.$$" "$BASE/current"
}
PROD="$HOME/myr-backend-releases/production"
DROP="$UNITS/myr-production-core.service.d/30-approved-release.conf"
STATE="$HOME/.config/myrinvoice/core-backend-deploy-in-progress"
gated_health() {
    local expected="$1" status
    for i in {1..20}; do
        if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8767/health 2>/dev/null | "$PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"]==(sys.argv[1]=="true")' "$expected" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8767/health | "$PY" -c 'import json,sys; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"]==(sys.argv[1]=="true")' "$expected" &&
    test "$(https -sS -o /dev/null -w '%{http_code}' https://myrinvoice.com/api/myr/workspace)" = 401 &&
    test "$(https -sS -o /dev/null -w '%{http_code}' https://myrinvoice.com/api/myr/native/auth/preview)" = 404 &&
    { if [ "$expected" = true ]; then status=404; else status=503; fi; } &&
    test "$(https -sS -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"p_token":"00000000000000000000000000000000"}' https://myrinvoice.com/api/myr/links/read)" = "$status"
}
deploy() {
    test -f "$MARKER" && test ! -L "$MARKER"
    test "$(stat -c '%a %U' "$MARKER")" = '600 myradmin'
    test ! -e "$STATE" || { echo 'Unfinished release; operator review required'; return 1; }
    pinned="$(cat "$MARKER")"
    [[ "$pinned" =~ ^[0-9a-f]{40}$ ]]
    systemctl --user is-active --quiet myr-production-core.service
    ! systemctl --user is-active --quiet myr-static-deploy.timer
    exec 9>"$BASE/deploy.lock"
    flock -w 90 9
    export GIT_TERMINAL_PROMPT=0
    export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15'
    git -C "$REPO" fetch --quiet --no-tags origin refs/heads/main:refs/remotes/origin/main refs/heads/core-production-approved:refs/remotes/origin/core-production-approved
    commit="$(git -C "$REPO" rev-parse --verify refs/remotes/origin/core-production-approved^{commit})"
    git -C "$REPO" merge-base --is-ancestor "$pinned" "$commit"
    git -C "$REPO" merge-base --is-ancestor "$commit" origin/main
    health
    if [ "$pinned" = "$commit" ]; then
        echo "MYR_CORE_BACKEND_UP_TO_DATE $commit"; return 0
    fi
    previous="$(readlink -f "$BASE/current")"
    case "$previous" in "$BASE/releases/vps-core-"*|"$BASE/releases/vps-frontend-"*) ;; *) echo 'Unexpected live root'; exit 1;; esac
    previous_commit="${previous##*-}"
    [[ "$previous_commit" =~ ^[0-9a-f]{40}$ ]]
    git -C "$REPO" merge-base --is-ancestor "$previous_commit" "$commit"
    # No automatic schema/route/dependency/credential changes. Approved Python code only.
    if ! git -C "$REPO" diff --quiet "$pinned" "$commit" -- supabase config.js vps/nginx-business-routing.review.conf; then
        echo "MYR_BACKEND_SCHEMA_OR_ROUTING_REVIEW_REQUIRED"; return 0
    fi
    if git -C "$REPO" diff --name-only "$pinned" "$commit" -- vps/backend | grep -Ev '\.py$' | grep -q .; then
        echo "MYR_BACKEND_NON_PYTHON_CHANGE_REQUIRES_REVIEW"; return 0
    fi
    stage="$(mktemp -d "$HOME/.myr-backend.XXXXXXXX")"
    webstage="$(mktemp -d "$BASE/releases/.frontend.XXXXXXXX")"
    release="$BASE/releases/vps-frontend-$commit"
    prod="$PROD/$commit"
    started=0
    rollback() {
        rc=$?
        trap - EXIT
        set +e
        if [ "$started" = 1 ]; then
            if [ "$(cat "$MARKER" 2>/dev/null)" = "$pinned" ]; then
                echo 'Restoring previous backend before writes reopen'
                if systemctl --user stop myr-production-core.service &&
                   { if [ -f "$STATE/old-dropin" ]; then install -m 0600 "$STATE/old-dropin" "$DROP"; else rm -f "$DROP"; fi; } &&
                   publish_link "$previous" &&
                   systemctl --user daemon-reload &&
                   systemctl --user start myr-production-core.service &&
                   gated_health true; then
                    rm -rf -- "$STATE"
                    echo 'MYR_CORE_BACKEND_ROLLBACK_OK'
                else
                    echo 'MYR_CORE_BACKEND_RECOVERY_REQUIRED' >&2
                    rc=1
                fi
            else
                echo 'MYR_CORE_BACKEND_POST_ACTIVATION_REVIEW_REQUIRED; do not restore database or marker blindly' >&2
                rc=1
            fi
        fi
        rm -rf -- "$stage" "$webstage"
        rm -f -- "$BASE/.core-frontend.$$" "$MARKER.next.$$"
        exit "$rc"
    }
    trap rollback EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    git -C "$REPO" archive "$commit" vps/backend "${ASSETS[@]}" | tar -xf - -C "$stage"
    test -z "$(find "$stage" -type l -print -quit)"
    MYR_BUSINESS_API_PREFIX=/api/myr MYR_CANDIDATE_DIR="$stage/candidate" "$PY" -B "$stage/vps/backend/build_cutover_check.py"
    git -C "$REPO" archive "$commit" "${ASSETS[@]}" | tar -xf - -C "$webstage"
    cp "$stage/candidate/index.html" "$stage/candidate/config.js" "$webstage/"
    "$PY" -B - "$webstage/index.html" <<'PYCODE'
import re,sys,subprocess
from pathlib import Path
index=Path(sys.argv[1])
html=index.read_text()
html=html.replace("PRIVATE VPS DATABASE CANDIDATE — Real imported data read-only. Production saves and external integrations disabled.","VPS CORE RELEASE — Advanced operations temporarily unavailable. LHDN and email are not connected.")
html=html.replace("persistSession:false","persistSession:true")
html=html.replace("Not available in read-only VPS staging","Not available in this core release")
html=html.replace("Unsupported rehearsal mutation","Advanced action unavailable in core release")
html=html.replace("This action is not connected in this rehearsal. Reload to discard local changes.","This advanced action is not available in this release. Reload to discard unsaved changes.")
# Preserve original SEO assets and network-only service worker.
html=html.replace("if(false&&'serviceWorker' in navigator", "if('serviceWorker' in navigator")

assert "from:()=>{throw new Error(" in html and "/api/myr/workspace" in html
assert "persistSession:true" in html
for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
    if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
        subprocess.run(["node","--check","-"],input=code,text=True,check=True)
index.write_text(html)
PYCODE
    node --check "$webstage/config.js"
    node --check "$webstage/concurrency.js"
    node --check "$webstage/sw.js"
    find "$webstage" -type d -exec chmod 0755 {} +
    find "$webstage" -type f -exec chmod 0644 {} +
    if [ -e "$release" ]; then
        diff -qr "$webstage" "$release" >/dev/null
    else
        mv "$webstage" "$release"
    fi
    # Run reviewed transaction-rollback tests without the production release environment.
    for testfile in check_business_asgi.py business_admin.py business_links.py business_link_ops.py business_api.py; do
        env -u MYR_PRODUCTION_RELEASE "$PY" -B "$stage/vps/backend/$testfile"
    done
    "$PY" -B "$stage/vps/backend/native_backup.py"
    mkdir -p "$PROD" "$(dirname "$DROP")"
    if [ ! -e "$prod" ]; then
        mkdir -m 0700 "$prod"
        mkdir -m 0700 "$prod/vps"
        cp -a "$stage/vps/backend" "$prod/vps/"
        cp "$stage/config.js" "$prod/config.js"
    else
        diff -qr -x __pycache__ "$stage/vps/backend" "$prod/vps/backend" >/dev/null
        cmp "$stage/config.js" "$prod/config.js"
    fi
    mkdir -m 0700 "$STATE"
    printf '%s\n' "$pinned" >"$STATE/previous-marker"
    printf '%s\n' "$previous" >"$STATE/previous-web"
    printf '%s\n' "$commit" >"$STATE/target"
    if [ -f "$DROP" ]; then cp "$DROP" "$STATE/old-dropin"; fi
    started=1
    # Stop and drain old service before replacing it. New release stays gated by old marker.
    systemctl --user stop myr-production-core.service
    cat >"$DROP" <<UNIT
[Service]
WorkingDirectory=$prod/vps/backend
Environment=MYR_PRODUCTION_RELEASE=$commit
UNIT
    systemctl --user daemon-reload
    systemctl --user start myr-production-core.service
    gated_health false
    publish_link "$release"
    https -fsS https://myrinvoice.com/ | cmp -s - "$release/index.html"
    # All checks passed. Same schema, no database restoration. Atomically open new release.
    printf '%s\n' "$commit" >"$MARKER.next.$$"
    chmod 0600 "$MARKER.next.$$"
    mv -T "$MARKER.next.$$" "$MARKER"
    gated_health true
    started=0
    rm -rf -- "$STATE"
    echo "MYR_CORE_BACKEND_RELEASE_DEPLOYED $commit"
}
if [ "${1:-}" = --run ]; then
    deploy
    exit 0
fi
test -f "$MARKER"
test -d "$REPO/.git"
health
mkdir -p "$(dirname "$BIN")" "$UNITS"
install -m 0700 "$0" "$BIN"
cat >"$UNITS/myr-core-backend-deploy.service" <<'UNIT'
[Unit]
Description=MYR Invoice approved production backend and frontend release
[Service]
Type=oneshot
ExecStart=%h/.local/bin/myr-core-backend-deploy --run
TimeoutStartSec=600
NoNewPrivileges=yes
UMask=0077
UNIT
cat >"$UNITS/myr-core-backend-deploy.timer" <<'UNIT'
[Unit]
Description=Check approved MYR production release every minute
[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
Unit=myr-core-backend-deploy.service
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user start myr-core-backend-deploy.service
test "$(cat "$MARKER")" = "$(git -C "$REPO" rev-parse origin/core-production-approved)"
systemctl --user enable --now myr-core-backend-deploy.timer
systemctl --user list-timers myr-core-backend-deploy.timer --no-pager
echo "MYR_CORE_BACKEND_AUTO_DEPLOY_READY"
echo "Approved branch only; automatic schema and routing changes prohibited."
