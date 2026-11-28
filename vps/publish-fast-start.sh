#!/usr/bin/env bash
# Publish only frontend startup performance fix by cloning the currently served frontend.
# Never restart services, change API routing, write database data or release candidate code.
set -euo pipefail
umask 022
test "$(id -un)" = myradmin
cd "$HOME/myr-invoices"
BASE=/var/www/myrinvoice.com/auto
MARKER="$HOME/.config/myrinvoice/production-writes-enabled"
AUTH="$HOME/.config/myrinvoice/native-auth-pilot-enabled"
PY="$HOME/myr-venv/bin/python"
PIN=4942c9562c5012c75ab75c10f116fefae039d48a
test "$(cat "$MARKER")" = "$PIN"
test "$(cat "$AUTH")" = "$PIN"
exec 9>"$BASE/deploy.lock"
flock -n 9
previous="$(readlink -f "$BASE/current")"
case "$previous" in "$BASE/releases/vps-core-"*|"$BASE/releases/vps-frontend-"*) ;; *) echo 'Unexpected live root'; exit 1;; esac
test -f "$previous/index.html"
test -z "$(find "$previous" -type l -print -quit)"
https() { curl --noproxy '*' --resolve myrinvoice.com:443:127.0.0.1 --max-time 15 "$@"; }
health() {
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8767/health | "$PY" -c 'import sys,json; x=json.load(sys.stdin); assert x["database"]=="vps" and x["writes_enabled"] is True' &&
    test "$(https -sS -o /dev/null -w '%{http_code}' https://myrinvoice.com/api/myr/workspace)" = 401
}
health
https -fsS https://myrinvoice.com/ | cmp -s - "$previous/index.html"
stage="$(mktemp -d "$BASE/releases/.fast-start.XXXXXXXX")"
link="$BASE/.fast-start.$$"
trap 'rm -rf -- "$stage"; rm -f -- "$link"' EXIT
cp -a "$previous/." "$stage/"
chmod 0755 "$stage"
"$PY" -B vps/backend/patch_fast_start.py "$stage/index.html"
cmp -s "$stage/config.js" "$previous/config.js"
release="$BASE/releases/vps-frontend-fast-start-$(git rev-parse --short=12 HEAD)-$(date +%s)"
test ! -e "$release"
mv "$stage" "$release"
publish() {
    ln -s "$1" "$link"
    mv -Tf "$link" "$BASE/current"
}
verify() {
    https -fsS https://myrinvoice.com/ | cmp -s - "$release/index.html" || return 1
    health || return 1
    for slug in refund-policy privacy-policy shipping-policy; do
        https -fsSL "https://myrinvoice.com/$slug" | grep -F "name=\"myr-policy-page\" content=\"$slug\"" >/dev/null || return 1
    done
    test "$(cat "$MARKER")" = "$PIN" && test "$(cat "$AUTH")" = "$PIN"
}
publish "$release"
if verify; then
    echo "MYR_FAST_START_LIVE_OK"
    https -sS -H "Accept-Encoding: gzip" -o /dev/null -w 'HTML response: %{time_starttransfer}s TTFB / %{time_total}s total / %{size_download} bytes\n' https://myrinvoice.com/
else
    publish "$previous"
    echo "MYR_FAST_START_DEPLOY_ROLLED_BACK" >&2
    exit 1
fi
