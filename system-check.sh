#!/bin/bash
# system-check.sh
# Full health check for bracas homelab
# Run on the server: bash /opt/homelab/system-check.sh

RESET='\033[0m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'

ok()   { echo -e "  ${GREEN}✔${RESET}  $1"; }
fail() { echo -e "  ${RED}✘${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
info() { echo -e "  ${BLUE}→${RESET}  $1"; }
section() { echo -e "\n${BOLD}━━━  $1  ━━━${RESET}"; }

# ── 1. System ──────────────────────────────────────────────────────────
section "System"

UPTIME=$(uptime -p)
ok "Uptime: $UPTIME"

# CPU load
LOAD=$(cut -d' ' -f1 /proc/loadavg)
CORES=$(nproc)
LOAD_INT=$(echo "$LOAD * 100 / $CORES" | bc 2>/dev/null || echo "0")
if (( $(echo "$LOAD > $CORES" | bc -l) )); then
  fail "CPU load high: $LOAD (cores: $CORES)"
else
  ok "CPU load: $LOAD (cores: $CORES)"
fi

# Memory
MEM_TOTAL=$(free -m | awk '/^Mem:/{print $2}')
MEM_USED=$(free -m | awk '/^Mem:/{print $3}')
MEM_PCT=$(( MEM_USED * 100 / MEM_TOTAL ))
if [ "$MEM_PCT" -gt 90 ]; then
  fail "Memory: ${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PCT}%)"
elif [ "$MEM_PCT" -gt 75 ]; then
  warn "Memory: ${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PCT}%)"
else
  ok "Memory: ${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PCT}%)"
fi

# Disk
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
DISK_INFO=$(df -h / | awk 'NR==2{print $3 " used of " $2 " (" $5 ")"}')
if [ "$DISK_PCT" -gt 90 ]; then
  fail "Disk /: $DISK_INFO"
elif [ "$DISK_PCT" -gt 75 ]; then
  warn "Disk /: $DISK_INFO"
else
  ok "Disk /: $DISK_INFO"
fi

# Swap
SWAP_USED=$(free -m | awk '/^Swap:/{print $3}')
SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')
if [ "$SWAP_TOTAL" -gt 0 ] && [ "$SWAP_USED" -gt $(( SWAP_TOTAL / 2 )) ]; then
  warn "Swap: ${SWAP_USED}MB / ${SWAP_TOTAL}MB used (high)"
else
  ok "Swap: ${SWAP_USED}MB / ${SWAP_TOTAL}MB used"
fi

# OS updates
UPDATES=$(apt list --upgradable 2>/dev/null | grep -c upgradable || echo 0)
if [ "$UPDATES" -gt 20 ]; then
  warn "$UPDATES packages upgradable"
elif [ "$UPDATES" -gt 0 ]; then
  info "$UPDATES packages upgradable"
else
  ok "System packages up to date"
fi

# ── 2. Docker containers ───────────────────────────────────────────────
section "Docker Containers"

EXPECTED=("homeassistant" "mosquitto" "digital-twin-api" "homepage" "dashboard-api" "glances")

for name in "${EXPECTED[@]}"; do
  STATUS=$(docker inspect --format='{{.State.Status}}' "$name" 2>/dev/null)
  RESTART=$(docker inspect --format='{{.RestartCount}}' "$name" 2>/dev/null)
  if [ -z "$STATUS" ]; then
    fail "$name — not found"
  elif [ "$STATUS" = "running" ]; then
    if [ "$RESTART" -gt 5 ]; then
      warn "$name — running (restarted ${RESTART}x — unstable)"
    else
      ok "$name — running"
    fi
  else
    fail "$name — $STATUS"
  fi
done

# Any unexpected containers
RUNNING=$(docker ps --format '{{.Names}}' | sort)
info "All running containers: $(echo $RUNNING | tr '\n' ' ')"

# ── 3. Services / ports ────────────────────────────────────────────────
section "Ports & Services"

check_port() {
  local name=$1 host=$2 port=$3
  if ss -tlnp | grep -q ":${port}"; then
    ok "$name — listening on :$port"
  else
    fail "$name — NOT listening on :$port"
  fi
}

check_port "Home Assistant"     "localhost" 8123
check_port "Mosquitto MQTT"     "localhost" 1883
check_port "Mosquitto WS"       "localhost" 9001
check_port "Digital Twin API"   "localhost" 8000
check_port "Homepage"           "localhost" 3000
check_port "Dashboard API"      "localhost" 8787
check_port "Glances"            "localhost" 61208
check_port "Caddy"              "localhost" 8088
check_port "Nextcloud"          "localhost" 80

# ── 4. API health checks ───────────────────────────────────────────────
section "API Health"

check_http() {
  local name=$1 url=$2 expect=$3
  RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null)
  if [ "$RESP" = "$expect" ]; then
    ok "$name — HTTP $RESP ($url)"
  else
    fail "$name — HTTP $RESP (expected $expect) ($url)"
  fi
}

check_http "Digital Twin API /health"   "http://localhost:8000/health"    "200"
check_http "Dashboard API /api/ha/summary" "http://localhost:8787/api/ha/summary" "200"
check_http "Home Assistant"             "http://localhost:8123"            "200"
check_http "Nextcloud"                  "http://localhost/login"           "200"

# Digital twin API detail
HA_STATUS=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('HA connected' if d.get('ha_connected') else 'HA disconnected')" 2>/dev/null || echo "parse error")
if [[ "$HA_STATUS" == "HA connected" ]]; then
  ok "Digital Twin → Home Assistant: connected"
else
  fail "Digital Twin → Home Assistant: $HA_STATUS"
fi

REGISTERED=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('registered_devices',0))" 2>/dev/null || echo "?")
ROOMS=$(curl -s --max-time 5 http://localhost:8000/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rooms',0))" 2>/dev/null || echo "?")
info "Twin: $REGISTERED registered devices, $ROOMS rooms"

# ── 5. Systemd services ────────────────────────────────────────────────
section "System Services"

check_service() {
  local svc=$1
  STATUS=$(systemctl is-active "$svc" 2>/dev/null)
  if [ "$STATUS" = "active" ]; then
    ok "$svc — active"
  else
    fail "$svc — $STATUS"
  fi
}

check_service "docker"
check_service "caddy"
check_service "tailscaled"
check_service "snap.nextcloud.apache"
check_service "snap.nextcloud.mysql"

# ── 6. Tailscale ──────────────────────────────────────────────────────
section "Tailscale"

TS_STATUS=$(tailscale status 2>/dev/null | head -1)
if tailscale status &>/dev/null; then
  ok "Tailscale connected"
  ONLINE=$(tailscale status --json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
peers=d.get('Peer',{})
on=sum(1 for p in peers.values() if p.get('Online'))
total=len(peers)
print(f'{on}/{total} peers online')
" 2>/dev/null || echo "?")
  info "Peers: $ONLINE"
else
  fail "Tailscale not connected"
fi

# ── 7. Nextcloud ──────────────────────────────────────────────────────
section "Nextcloud"

NC_DATA="/var/snap/nextcloud/common/nextcloud/data"
if [ -d "$NC_DATA" ]; then
  NC_SIZE=$(du -sh "$NC_DATA" 2>/dev/null | cut -f1)
  ok "Data dir exists: $NC_DATA ($NC_SIZE)"
else
  fail "Data dir not found: $NC_DATA"
fi

# ── 8. Git status ─────────────────────────────────────────────────────
section "Git Repository"

if [ -d "/opt/homelab/.git" ]; then
  cd /opt/homelab
  BRANCH=$(git branch --show-current 2>/dev/null)
  UNCOMMITTED=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  UNPUSHED=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l | tr -d ' ')

  ok "Repo initialized — branch: $BRANCH"

  if [ "$UNCOMMITTED" -gt 0 ]; then
    warn "$UNCOMMITTED uncommitted change(s)"
    git status --short | head -10 | while read line; do info "  $line"; done
  else
    ok "Working tree clean"
  fi

  if [ "$UNPUSHED" -gt 0 ]; then
    warn "$UNPUSHED commit(s) not pushed to GitHub"
  else
    ok "Up to date with remote"
  fi
else
  fail "No git repo at /opt/homelab"
fi

# ── 9. Security ───────────────────────────────────────────────────────
section "Security"

# Check for exposed secrets
if find /opt/homelab -name "*.env" | xargs grep -l "TOKEN\|PASSWORD\|SECRET" 2>/dev/null | grep -qv ".gitignore"; then
  warn ".env files with secrets exist (confirm they are gitignored)"
else
  ok "No exposed secrets detected in tracked files"
fi

# Caddy binding check
if grep -q "http://100\." /opt/homelab/caddy/Caddyfile 2>/dev/null; then
  ok "Caddy bound to Tailscale IP only"
elif grep -q "http://:" /opt/homelab/caddy/Caddyfile 2>/dev/null; then
  warn "Caddy bound to all interfaces — consider restricting to Tailscale IP"
else
  info "Caddy config: $(head -1 /opt/homelab/caddy/Caddyfile 2>/dev/null)"
fi

# SSH root login
ROOT_LOGIN=$(sshd -T 2>/dev/null | grep "^permitrootlogin" | awk '{print $2}')
if [ "$ROOT_LOGIN" = "no" ] || [ "$ROOT_LOGIN" = "prohibit-password" ]; then
  ok "SSH root login: $ROOT_LOGIN"
else
  warn "SSH root login: $ROOT_LOGIN (consider disabling)"
fi

# ── 10. Recent errors ─────────────────────────────────────────────────
section "Recent Docker Errors (last 50 lines)"

for name in "digital-twin-api" "dashboard-api" "homeassistant"; do
  ERRORS=$(docker logs "$name" --tail=50 2>&1 | grep -iE "error|exception|traceback|critical" | tail -3)
  if [ -n "$ERRORS" ]; then
    warn "$name has recent errors:"
    echo "$ERRORS" | while read line; do info "  $line"; done
  else
    ok "$name — no errors in last 50 log lines"
  fi
done

# ── Summary ───────────────────────────────────────────────────────────
section "Done"
echo -e "  Run ${BOLD}docker logs <name> --tail=100${RESET} to investigate any failing container"
echo -e "  Run ${BOLD}sudo journalctl -xe${RESET} for system-level errors"
echo ""
