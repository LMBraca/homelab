#!/usr/bin/env bash
set -euo pipefail

OUT="$(cd "$(dirname "$0")" && pwd)/homepage/generated/tailscale.yaml"
mkdir -p "$(dirname "$OUT")"
json="$(tailscale status --json)"

python3 - <<'PY' "$OUT" "$json"
import json, sys

out = sys.argv[1]
data = json.loads(sys.argv[2])

peers = (data.get("Peer") or {})
items = []

for _, p in peers.items():
    dns = (p.get("DNSName") or "").rstrip(".")              # remove trailing dot
    host = (p.get("HostName") or "")
    nm = (p.get("Name") or "")

# Prefer MagicDNS name, then hostname, then name
    name = dns if dns else (host if host else (nm if nm else "unknown"))

# Strip your tailnet suffix to keep it clean
    name = name.replace(".tailb8843e.ts.net", "")
    ip = (p.get("TailscaleIPs") or [""])[0]
    online = bool(p.get("Online", False))
    last = p.get("LastSeen")
    status = "ONLINE" if online else f"OFFLINE (last {last})"
    items.append((0 if online else 1, name.lower(), name, ip, status))

items.sort()
seen = set()
deduped = []
for t in items:
    _, __, n, ip, status = t
    key = (n, ip)
    if key in seen:
        continue
    seen.add(key)
    deduped.append(t)
items = deduped
lines = []
from datetime import datetime, timezone
lines.append(f"# generated: {datetime.now(timezone.utc).isoformat()}")
lines.append("- Network:")
for _, __, name, ip, status in items[:30]:
    # One service entry per device (this is what Homepage expects)
    lines.append(f"    - {name}:")
    lines.append(f"        description: \"{ip} — {status}\"")

open(out, "w").write("\n".join(lines) + "\n")
PY
