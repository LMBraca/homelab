#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

"$BASE/generate_tailscale_services.sh"

cat "$BASE/homepage/services.static.yaml" \
    "$BASE/homepage/generated/tailscale.yaml" \
  > "$TMP"

# Only replace services.yaml if content changed
if ! cmp -s "$TMP" "$BASE/homepage/services.yaml"; then
  mv "$TMP" "$BASE/homepage/services.yaml"
else
  rm -f "$TMP"
fi
