#!/usr/bin/env bash
# Read-only readiness inventory; this script NEVER switches DNS or exposes the preview.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
for service in nginx postgresql fail2ban unattended-upgrades; do
 if systemctl is-active --quiet "$service"; then echo "ACTIVE: $service"; else echo "REVIEW: $service inactive"; fi
done
for cmd in nginx certbot node; do
 if command -v "$cmd" >/dev/null 2>&1; then echo "AVAILABLE: $cmd"; else echo "REVIEW: $cmd missing or not on PATH"; fi
done
echo "Disk capacity:"
df -h "$HOME"
echo "Current private release: $(git rev-parse --short HEAD)"
echo "Listening TCP sockets:"
ss -H -ltn
echo "VPS_DEPLOYMENT_INVENTORY_OK"
echo "BLOCKERS: real browser acceptance; remaining business/auth workflows; independent offsite destination and key escrow; verified source-data reconciliation and public HTTPS/rollback."
echo "No DNS, firewall or public web configuration was changed."
