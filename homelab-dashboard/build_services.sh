#!/usr/bin/env bash
set -euo pipefail

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

/opt/homelab-dashboard/generate_tailscale_services.sh

cat /opt/homelab-dashboard/homepage/services.static.yaml \
    /opt/homelab-dashboard/homepage/generated/tailscale.yaml \
  > "$TMP"

# Only replace services.yaml if content changed
if ! cmp -s "$TMP" /opt/homelab-dashboard/homepage/services.yaml; then
  mv "$TMP" /opt/homelab-dashboard/homepage/services.yaml
else
  rm -f "$TMP"
fi
