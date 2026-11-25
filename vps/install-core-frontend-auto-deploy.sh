#!/usr/bin/env bash
# Production frontend updates only. Keep the verified backend and write marker pinned.
set -euo pipefail
umask 077
test "$(id -un)" = myradmin
REPO="$HOME/myr-invoices"
BASE=/var/www/myrinvoice.com/auto
MARKER="$HOME/.config/myrinvoice/production-writes-enabled"
PY="$HOME/myr-venv/bin/python"
BIN="$HOME/.local/bin/myr-core-frontend-deploy"
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
deploy() {
    test -f "$MARKER" && test ! -L "$MARKER"
    test "$(stat -c '%a %U' "$MARKER")" = '600 myradmin'
    pinned="$(cat "$MARKER")"
    [[ "$pinned" =~ ^[0-9a-f]{40}$ ]]
    systemctl --user is-active --quiet myr-production-core.service
    if systemctl --user is-active --quiet myr-static-deploy.timer; then
        echo "Unsafe legacy timer active; refuse." >&2; exit 1
    fi
    exec 9>"$BASE/deploy.lock"
    flock -n 9 || exit 0
    export GIT_TERMINAL_PROMPT=0
    export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15'
    git -C "$REPO" fetch --quiet --no-tags origin refs/heads/main:refs/remotes/origin/main
    commit="$(git -C "$REPO" rev-parse --verify refs/remotes/origin/main^{commit})"
    git -C "$REPO" merge-base --is-ancestor "$pinned" "$commit"
    previous="$(readlink -f "$BASE/current")"
    case "$previous" in "$BASE/releases/vps-core-"*|"$BASE/releases/vps-frontend-"*) ;; *) echo 'Unexpected live root'; exit 1;; esac
    health
    # Runtime code/config/routing are pinned. Any backend change requires its own reviewed release.
    if ! git -C "$REPO" diff --quiet "$pinned" "$commit" -- vps/backend vps/nginx-business-routing.review.conf config.js supabase; then
        echo "MYR_BACKEND_CHANGE_REQUIRES_REVIEW $commit"; return 0
    fi
    release="$BASE/releases/vps-frontend-$commit"
    if [ "$previous" = "$release" ]; then
        echo "MYR_CORE_FRONTEND_UP_TO_DATE $commit"; return 0
    fi
    stage="$(mktemp -d "$HOME/.myr-frontend.XXXXXXXX")"
    webstage="$(mktemp -d "$BASE/releases/.frontend.XXXXXXXX")"
    trap 'rm -rf -- "$stage" "$webstage"; rm -f -- "$BASE/.core-frontend.$$"' EXIT
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
    publish_link "$release"
    if https -fsS https://myrinvoice.com/ | cmp -s - "$release/index.html" && health; then
        echo "MYR_CORE_FRONTEND_DEPLOYED $commit"
    else
        publish_link "$previous"
        health
        echo "MYR_CORE_FRONTEND_ROLLED_BACK $commit" >&2
        return 1
    fi
}
if [ "${1:-}" = --run ]; then
    deploy; exit 0
fi
test -f "$MARKER"
test -d "$REPO/.git"
systemctl --user is-active --quiet myr-production-core.service
health
systemctl --user disable --now myr-static-deploy.timer
systemctl --user stop myr-static-deploy.service
mkdir -p "$(dirname "$BIN")" "$UNITS"
install -m 0700 "$0" "$BIN"
cat >"$UNITS/myr-core-frontend-deploy.service" <<'UNIT'
[Unit]
Description=MYR Invoice verified VPS-compatible frontend release
[Service]
Type=oneshot
ExecStart=%h/.local/bin/myr-core-frontend-deploy --run
TimeoutStartSec=300
NoNewPrivileges=yes
UMask=0077
UNIT
cat >"$UNITS/myr-core-frontend-deploy.timer" <<'UNIT'
[Unit]
Description=Check private GitHub main for VPS-compatible frontend releases
[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
Unit=myr-core-frontend-deploy.service
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user start myr-core-frontend-deploy.service
test "$(readlink -f "$BASE/current")" = "$BASE/releases/vps-frontend-$(git -C "$REPO" rev-parse origin/main)"
systemctl --user enable --now myr-core-frontend-deploy.timer
systemctl --user list-timers myr-core-frontend-deploy.timer --no-pager
echo "MYR_CORE_FRONTEND_AUTO_DEPLOY_READY"
echo "Backend, authentication, schema and database write marker unchanged."
