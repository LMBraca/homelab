#!/bin/bash
# ============================================================
# alert-claude-limits.sh
# Reads /opt/claude-ideas/limits.json and tracks how many
# consecutive checks each account has been in an error state.
# Fires a notification when an account's streak reaches the
# threshold (default: 2) — meaning a single transient failure
# won't page you, but a sustained problem will.
#
# State is kept in /opt/claude-ideas/alert-state.json:
#   {"1": {"streak": 0, "alerted": false},
#    "2": {"streak": 3, "alerted": true,  "last_error": "..."},
#    ...}
#
# Add to crontab to run hourly, a few minutes after the fetcher:
#   5 * * * * /opt/homelab/scripts/claude-ideas/alert-claude-limits.sh
# ============================================================

LIMITS_FILE="/opt/claude-ideas/limits.json"
STATE_FILE="/opt/claude-ideas/alert-state.json"
LOG_FILE="/opt/claude-ideas/alert.log"
# Thresholds pulled from /opt/claude-ideas/settings.json so the dashboard
# /settings page can retune alerting without editing this file.
SETTINGS_FILE="${SETTINGS_FILE:-/opt/claude-ideas/settings.json}"
_read_setting() {
    python3 - "$SETTINGS_FILE" "$1" "$2" "$3" <<'PYEOF' 2>/dev/null || echo "$3"
import json, sys
path, section, key, default = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(path) as f:
        d = json.load(f)
    v = d.get(section, {}).get(key)
    print(v if v not in (None, "") else default)
except Exception:
    print(default)
PYEOF
}
THRESHOLD=$(_read_setting generator alert_failure_threshold 2)
REFRESH_STALE_HOURS=$(_read_setting generator alert_stale_hours 36)
# (keepalive runs daily, hourly fetcher refreshes proactively within 15m of
# token expiry, so a healthy system tops .last_refresh every few hours; the
# default 36h covers a full keepalive cycle + buffer.)
mkdir -p /opt/claude-ideas

# ── notify() ────────────────────────────────────────────────
# Single place to swap your notification channel. Default:
# log to file + broadcast via `wall` (visible on any open ssh session).
# To add ntfy: uncomment the ntfy block and set NTFY_URL.
# To add Home Assistant: uncomment the HA block and set HA_URL/HA_TOKEN.
notify() {
    local title="$1"
    local body="$2"
    local stamp
    stamp="[$(date '+%Y-%m-%d %H:%M:%S')]"
    echo "$stamp ALERT: $title — $body" | tee -a "$LOG_FILE"

    # Desktop / shell broadcast (always on)
    echo "$stamp $title: $body" | wall 2>/dev/null || true

    # ── ntfy.sh ────────────────────────────────────────────
    # NTFY_URL="https://ntfy.sh/your-topic-here"
    # if [[ -n "$NTFY_URL" ]]; then
    #     curl -s -H "Title: $title" -d "$body" "$NTFY_URL" >/dev/null
    # fi

    # ── Home Assistant ─────────────────────────────────────
    # HA_URL="http://localhost:8123"
    # HA_TOKEN="your-long-lived-token"
    # if [[ -n "$HA_TOKEN" ]]; then
    #     curl -s -X POST \
    #         -H "Authorization: Bearer $HA_TOKEN" \
    #         -H "Content-Type: application/json" \
    #         -d "{\"title\":\"$title\",\"message\":\"$body\"}" \
    #         "$HA_URL/api/services/notify/notify" >/dev/null
    # fi
}
export -f notify
export LOG_FILE

python3 - "$LIMITS_FILE" "$STATE_FILE" "$THRESHOLD" "$REFRESH_STALE_HOURS" <<'PYEOF'
import json
import os
import sys
import subprocess
from datetime import datetime

LIMITS_FILE         = sys.argv[1]
STATE_FILE          = sys.argv[2]
THRESHOLD           = int(sys.argv[3])
REFRESH_STALE_HOURS = int(sys.argv[4])
REFRESH_STALE_SEC   = REFRESH_STALE_HOURS * 3600


def notify(title, body):
    """Call the bash notify() function exported from the wrapper."""
    subprocess.run(
        ["bash", "-c", 'notify "$1" "$2"', "_", title, body],
        check=False,
    )


# Load existing state (fresh dict if missing or corrupt)
state = {}
if os.path.isfile(STATE_FILE):
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        state = {}

# Read current limits — if the file itself is missing, that's its own alert
if not os.path.isfile(LIMITS_FILE):
    notify(
        "Claude limits.json missing",
        f"{LIMITS_FILE} does not exist. fetch-claude-limits.sh may not be running.",
    )
    sys.exit(0)

try:
    with open(LIMITS_FILE) as f:
        limits = json.load(f)
except Exception as e:
    notify("Claude limits.json unreadable", f"Could not parse {LIMITS_FILE}: {e}")
    sys.exit(0)

# Inspect each account
for acct in ("1", "2", "3"):
    entry = limits.get(acct, {})
    err = entry.get("error")
    s = state.setdefault(acct, {"streak": 0, "alerted": False, "last_error": None})

    if err:
        s["streak"] = s.get("streak", 0) + 1
        s["last_error"] = err
        # Alert exactly once per sustained outage
        if s["streak"] >= THRESHOLD and not s.get("alerted"):
            notify(
                f"Claude account {acct} unhealthy",
                f"Limits fetch has failed {s['streak']} consecutive times. "
                f"Last error: {err}. "
                f"Re-login with: CLAUDE_CONFIG_DIR=~/.claude-account-{acct} claude login",
            )
            s["alerted"] = True
    else:
        # Recovered — if we previously alerted, send a recovery note
        if s.get("alerted"):
            notify(
                f"Claude account {acct} recovered",
                f"Limits are loading again after {s.get('streak', 0)} failed checks.",
            )
        s["streak"] = 0
        s["alerted"] = False
        s["last_error"] = None

    # ── Refresh-pipeline health check ─────────────────────────────────
    # This is the leading indicator the 2026-04-22..24 silent outage
    # lacked. .last_refresh is touched only on a SUCCESSFUL OAuth
    # rotation. When refresh breaks, this stamp goes stale immediately
    # — whereas `err` above only appears once access tokens actually
    # age out and /api/oauth/usage starts 401-ing (24-48h later).
    # Tracked with its own streak/alert slot so it doesn't collide
    # with the usage-error state above.
    rs = state.setdefault(
        f"{acct}_refresh",
        {"streak": 0, "alerted": False, "last_age_sec": None},
    )
    age_sec = entry.get("last_refresh_age_seconds")
    # age_sec being None means .last_refresh is missing — same
    # severity as "way too old" for our purposes.
    is_stale = (age_sec is None) or (age_sec > REFRESH_STALE_SEC)
    if is_stale:
        rs["streak"] = rs.get("streak", 0) + 1
        rs["last_age_sec"] = age_sec
        if rs["streak"] >= THRESHOLD and not rs.get("alerted"):
            if age_sec is None:
                detail = f"No .last_refresh stamp on account {acct} — refresh has never succeeded."
            else:
                hours = age_sec // 3600
                detail = (
                    f"Last successful OAuth refresh was {hours}h ago "
                    f"(threshold {REFRESH_STALE_HOURS}h)."
                )
            notify(
                f"Claude account {acct} refresh stale",
                detail
                + " Tokens will start 401-ing once access-token lifetime runs out. "
                  "Check /opt/claude-ideas/keepalive.log; if OAuth is broken re-run "
                  f"/opt/homelab/scripts/claude-ideas/setup-claude-accounts.sh for account {acct}.",
            )
            rs["alerted"] = True
    else:
        if rs.get("alerted"):
            notify(
                f"Claude account {acct} refresh recovered",
                f"OAuth refresh succeeded — .last_refresh is {age_sec//60}m old.",
            )
        rs["streak"] = 0
        rs["alerted"] = False
        rs["last_age_sec"] = age_sec

# Persist state atomically
tmp = STATE_FILE + ".tmp"
with open(tmp, "w") as f:
    json.dump(state, f, indent=2)
os.replace(tmp, STATE_FILE)
PYEOF
