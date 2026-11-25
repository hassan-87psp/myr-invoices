#!/usr/bin/env bash
# Pull-based static production deployment. No root execution of fetched code,
# no public API proxy, no database migration, no GitHub runner or new secret.
set -euo pipefail
umask 022
REPO="$HOME/myr-invoices"
BASE=/var/www/myrinvoice.com/auto
CONF=/etc/nginx/sites-available/myrinvoice.com
BIN="$HOME/.local/bin/myr-static-deploy"
UNITS="$HOME/.config/systemd/user"

deploy() {
    test "$(id -un)" = myradmin
    export GIT_TERMINAL_PROMPT=0
    export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15'
    mkdir -p "$BASE/releases"
    exec 9>"$BASE/deploy.lock"
    flock -n 9 || exit 0
    git -C "$REPO" fetch --quiet --no-tags origin refs/heads/main:refs/remotes/origin/main
    commit="$(git -C "$REPO" rev-parse --verify refs/remotes/origin/main^{commit})"
    release="$BASE/releases/$commit"
    if [ "$(readlink "$BASE/current" || true)" = "$release" ]; then
        echo "MYR_STATIC_UP_TO_DATE $commit"
        return
    fi
    stage="$(mktemp -d "$BASE/releases/.build.XXXXXXXX")"
    link="$BASE/.current.$$"
    trap 'rm -rf -- "$stage"; rm -f -- "$link"' EXIT
    git -C "$REPO" archive --format=tar "$commit" \
      index.html config.js concurrency.js klcc-skyline.webp myr-auth-night.svg \
      manifest.webmanifest pwa-icon-192.png pwa-icon-512.png robots.txt seo.css sitemap.xml sw.js \
      e-invoice-malaysia/index.html invoice-app-malaysia/index.html \
      invoice-generator-malaysia/index.html invoice-software-malaysia/index.html \
      invoicing-software-for-small-business-malaysia/index.html myinvois-checklist/index.html \
      | tar -xf - -C "$stage"
    test -z "$(find "$stage" -type l -print -quit)"
    test -s "$stage/index.html"
    # Parse but do not execute JavaScript from the fetched commit.
    node - "$stage" <<'NODE'
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const base = process.argv[2];
const config = fs.readFileSync(path.join(base,'config.js'),'utf8');
if (/sb_secret_[a-z0-9_-]+/i.test(config)) throw Error('Private key detected in public config');
const match = config.match(/supabaseAnonKey\s*:\s*['"]([^'"]+)['"]/);
if (!match) throw Error('Missing public key');
if (!match[1].startsWith('sb_publishable_')) {
 const claims=JSON.parse(Buffer.from(match[1].split('.')[1]||'','base64url').toString());
 if(claims.role!=='anon') throw Error('Non-anon key in public config');
}
for (const name of ['config.js','concurrency.js','sw.js']) new vm.Script(fs.readFileSync(path.join(base,name),'utf8'),{filename:name});
const html = fs.readFileSync(path.join(base,'index.html'),'utf8');
if (!/<html\b/i.test(html) || !/<script\s+src="config.js">/i.test(html)) throw Error('Invalid app document');
const scripts=[...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)].filter(m=>!/\bsrc\s*=/.test(m[1]));
if (!scripts.length) throw Error('Missing application scripts');
for (const [i,m] of scripts.entries()) {
 if (/application\/ld\+json/i.test(m[1])) JSON.parse(m[2]);
 else if (!/application\/json/i.test(m[1])) new vm.Script(m[2],{filename:'inline-'+i+'.js'});
}
NODE
    find "$stage" -type d -exec chmod 0755 {} +
    find "$stage" -type f -exec chmod 0644 {} +
    if [ -e "$release" ]; then
        diff -qr "$stage" "$release" >/dev/null
    else
        mv -- "$stage" "$release"
    fi
    ln -s "$release" "$link"
    mv -Tf -- "$link" "$BASE/current"
    echo "MYR_STATIC_RELEASE_DEPLOYED $commit"
}
if [ "${1:-}" = --run ]; then
    deploy
    exit 0
fi

test "$(id -un)" = myradmin
test -d "$REPO/.git"
test -f "$CONF"
command -v node >/dev/null
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0755 "$BASE"
mkdir -p "$(dirname "$BIN")" "$UNITS"
install -m 0700 "$0" "$BIN"
cat >"$UNITS/myr-static-deploy.service" <<'UNIT'
[Unit]
Description=MYR Invoice GitHub static website deployment
[Service]
Type=oneshot
ExecStart=%h/.local/bin/myr-static-deploy --run
TimeoutStartSec=180
UMask=0022
UNIT
cat >"$UNITS/myr-static-deploy.timer" <<'UNIT'
[Unit]
Description=Check GitHub main for MYR Invoice website releases every minute
[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
Unit=myr-static-deploy.service
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
# This proves the service can fetch with no interactive credential prompt.
systemctl --user start myr-static-deploy.service
test -s "$BASE/current/index.html"
if ! sudo grep -Fq "root $BASE/current;" "$CONF"; then
    sudo grep -Fq 'root /var/www/myrinvoice.com/public;' "$CONF"
    backup="$CONF.pre-auto-$(date +%Y%m%d-%H%M%S)"
    sudo cp -a "$CONF" "$backup"
    sudo sed -i "s@root /var/www/myrinvoice.com/public;@root $BASE/current;@" "$CONF"
    if ! sudo nginx -t || ! sudo systemctl reload nginx; then
        sudo cp -a "$backup" "$CONF"
        sudo nginx -t && sudo systemctl reload nginx
        exit 1
    fi
    if ! curl --noproxy '*' -fsS --max-time 15 --resolve myrinvoice.com:443:127.0.0.1 https://myrinvoice.com/ | cmp -s - "$BASE/current/index.html"; then
        sudo cp -a "$backup" "$CONF"
        sudo nginx -t && sudo systemctl reload nginx
        echo "Local HTTPS check failed; restored previous site configuration."
        exit 1
    fi
fi
if [ "$(loginctl show-user "$(id -un)" -p Linger --value)" != yes ]; then
    sudo loginctl enable-linger "$(id -un)"
fi
systemctl --user enable --now myr-static-deploy.timer
systemctl --user list-timers myr-static-deploy.timer --no-pager
echo "MYR_GITHUB_AUTO_DEPLOY_READY"
echo "Static frontend only; Supabase database, private VPS APIs and migrations unchanged."
