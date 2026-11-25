#!/usr/bin/env bash
# Prepare a private, localhost-only staging release. Never change live DNS.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin || { echo "Run as myradmin, not root"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Working tree has changes; stop"; exit 1; }
for service in nginx postgresql fail2ban unattended-upgrades; do
  systemctl is-active --quiet "$service" || { echo "$service inactive"; exit 1; }
done
test -x "$HOME/myr-venv/bin/python"
"$HOME/myr-venv/bin/python" -c 'import fastapi, uvicorn, psycopg, argon2, dotenv'
umask 077
mkdir -p "$HOME/myr-staging/releases"
release="$(git rev-parse HEAD)"
target="$HOME/myr-staging/releases/$release"
if [ ! -d "$target" ]; then
  tmp="$(mktemp -d "$HOME/myr-staging/releases/.tmp.XXXXXX")"
  trap 'rm -rf -- "$tmp"' EXIT
  # Explicit public asset allowlist; never expose .git, SQL, config or secrets.
  for f in index.html concurrency.js klcc-skyline.webp manifest.webmanifest myr-auth-night.svg pwa-icon-192.png pwa-icon-512.png seo.css; do
    test -f "$f" && cp -- "$f" "$tmp/"
  done
  for d in e-invoice-malaysia invoice-app-malaysia invoice-generator-malaysia invoicing-software-malaysia invoicing-software-for-small-business-malaysia myinvois-checklist; do
    if [ -f "$d/index.html" ]; then mkdir "$tmp/$d"; cp "$d/index.html" "$tmp/$d/"; fi
  done
  # Disable live cloud credentials and demo mode. Staging is not a functional backend yet.
  printf '%s\n' 'window.MYR_CONFIG = {allowDemo:false};' > "$tmp/config.js"
  printf '%s\n' 'User-agent: *' 'Disallow: /' > "$tmp/robots.txt"
  mv -- "$tmp" "$target"
  trap - EXIT
fi
ln -sfn "$target" "$HOME/myr-staging/current"
echo "STAGING_PREPARED $release"
echo "No public hosting, database writes or production changes performed."
