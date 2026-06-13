#!/bin/bash
# ============================================================
# Fetches session + weekly usage limits from api.claude.ai
# for each Claude account and writes to:
#   /opt/claude-ideas/limits.json
#
# Refreshes expired OAuth access tokens automatically using the
# refresh_token — otherwise short-lived access tokens would start
# returning HTTP 401 after ~1 hour and limits.json would be useless.
#
# Token refreshes are serialized via flock on each account's
# .credentials.json so this script and the keep-alive script can
# never race with each other (or with themselves under overlapping
# cron runs). The dashboard API (app.py) is read-only on creds —
# this script is the single writer.
#
# Run from host (not Docker) — requires internet access.
# Add to crontab to run hourly:
#   0 * * * * /opt/homelab/scripts/claude-ideas/fetch-claude-limits.sh
# ============================================================

OUTPUT="/opt/claude-ideas/limits.json"
mkdir -p /opt/claude-ideas

# CLAUDE_HOME defaults to $HOME (host runs as luis). Override when invoking
# from contexts where HOME isn't /home/luis (e.g. the dashboard container
# shelling out to this script).
CLAUDE_HOME="${CLAUDE_HOME:-$HOME}"

python3 - "$CLAUDE_HOME" "$OUTPUT" <<'PYEOF'
import json
import os
import sys
import fcntl
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

HOME = sys.argv[1]
OUTPUT = sys.argv[2]

USAGE_URL   = "https://api.anthropic.com/api/oauth/usage"
# OAuth token endpoint moved from auth.anthropic.com to platform.claude.com
# in early 2026. The old hostname no longer resolves (NXDOMAIN), which is
# what broke the keep-alive script after the 2026-04-21 outage.
# Source of truth: TOKEN_URL constant in the bundled Claude Code CLI.
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"

# Claude Code's public OAuth client_id. The /v1/oauth/token endpoint returns
# 400 "Invalid request format" when the refresh_token grant is posted without
# it — confirmed empirically 2026-04-24. Source of truth: CLIENT_ID constant
# in the bundled @anthropic-ai/claude-code cli.js.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

COMMON_HEADERS = {
    "Authorization": "",  # filled in per-request
    "Content-Type": "application/json",
    "User-Agent": "claude-code",
    "anthropic-beta": "oauth-2025-04-20",
}

# Refresh proactively when access token has < 15 minutes of life left.
# This keeps the refresh token regularly exercised (so it doesn't expire
# from idleness) without refreshing every single tick.
REFRESH_LEAD_MS = 15 * 60 * 1000


def refresh_access_token(creds_path, creds):
    """Exchange refresh_token for a new access_token, persist back to disk."""
    oauth = creds.get("claudeAiOauth", {})
    refresh_token = oauth.get("refreshToken", "")
    if not refresh_token:
        return None

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    })

    # Shell out to curl instead of using urllib: Cloudflare fronts
    # platform.claude.com with TLS-fingerprint-based bot detection (error
    # 1010) that blocks Python's urllib regardless of what HTTP headers we
    # set on top — it's the OpenSSL ClientHello signature being flagged,
    # not the User-Agent. curl's TLS fingerprint passes. Using the system
    # curl here avoids adding a curl_cffi / httpx-impersonation dep.
    # --fail-with-body gives nonzero exit on 4xx/5xx while still returning
    # the response body, so we can surface error_description on failure.
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "--fail-with-body", "--max-time", "15",
                "-X", "POST",
                "-H", "Content-Type: application/json",
                "-H", "User-Agent: claude-code",
                "-H", "anthropic-beta: oauth-2025-04-20",
                "--data", payload,
                REFRESH_URL,
            ],
            capture_output=True,
            timeout=20,
        )
    except Exception as e:
        print(f"[refresh] subprocess error: {e}", file=sys.stderr)
        return None

    if result.returncode != 0:
        body = result.stdout.decode(errors="replace")[:500]
        err  = result.stderr.decode(errors="replace")[:200]
        print(f"[refresh] curl exit {result.returncode}: {body} | {err}", file=sys.stderr)
        return None

    raw = result.stdout

    new_tokens = json.loads(raw)
    new_access  = new_tokens.get("access_token", "")
    new_refresh = new_tokens.get("refresh_token", refresh_token)
    new_expires = new_tokens.get("expires_in")  # seconds from now

    if not new_access:
        return None

    oauth["accessToken"]  = new_access
    oauth["refreshToken"] = new_refresh
    if new_expires:
        oauth["expiresAt"] = int((datetime.now(timezone.utc).timestamp() + new_expires) * 1000)
    creds["claudeAiOauth"] = oauth

    # Atomic write: tmp file + rename, so a crash mid-write can't corrupt creds.
    tmp_path = creds_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(creds, f, indent=2)
        os.replace(tmp_path, creds_path)
        # Stamp last-refresh time alongside so we can monitor refresh-token health.
        stamp_path = os.path.join(os.path.dirname(creds_path), ".last_refresh")
        with open(stamp_path, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except Exception:
        # If we can't persist, the token is still usable for this run.
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return new_access


def get_valid_token_locked(creds_path):
    """Return a non-expired access token, refreshing if needed.
    Holds an exclusive flock on the creds file across the entire
    read/refresh/write sequence so concurrent runs cannot stomp each other.
    """
    # Open in r+ so we can flock the actual creds file (not a sidecar).
    with open(creds_path, "r+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            creds = json.load(fh)
            oauth = creds.get("claudeAiOauth", {})
            access_token = oauth.get("accessToken", "")
            expires_at   = oauth.get("expiresAt", 0)  # ms epoch

            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            if access_token and expires_at and (expires_at - now_ms) > REFRESH_LEAD_MS:
                return access_token

            refreshed = refresh_access_token(creds_path, creds)
            return refreshed or access_token
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def last_refresh_age_seconds(config_dir):
    """Seconds since .last_refresh was written (None if file missing).
    Surfaced in limits.json so the dashboard + alerter can treat a
    silently-failing refresh pipeline as a first-class health signal,
    not wait for access tokens to age out and start 401-ing."""
    stamp_path = os.path.join(config_dir, ".last_refresh")
    try:
        return int(datetime.now(timezone.utc).timestamp() - os.path.getmtime(stamp_path))
    except FileNotFoundError:
        return None
    except Exception:
        return None


def fetch_one(acct):
    config_dir = os.path.join(HOME, f".claude-account-{acct}")
    creds_path = os.path.join(config_dir, ".credentials.json")

    if not os.path.isfile(creds_path):
        return {"error": "no credentials"}

    try:
        token = get_valid_token_locked(creds_path)
    except Exception as e:
        return {"error": f"token read failed: {e}"}

    if not token:
        return {"error": "no token"}

    headers = dict(COMMON_HEADERS)
    headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(USAGE_URL, headers=headers)
    try:
        raw = urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:
        return {
            "error": f"HTTP Error {e.code}: {e.reason}",
            "last_refresh_age_seconds": last_refresh_age_seconds(config_dir),
        }
    except Exception as e:
        return {
            "error": str(e),
            "last_refresh_age_seconds": last_refresh_age_seconds(config_dir),
        }

    try:
        payload = json.loads(raw)
    except Exception as e:
        return {"error": f"bad json: {e}", "raw": raw.decode(errors="replace")[:300]}

    return {
        "data": payload,
        "fetched_at": datetime.now().isoformat(),
        "last_refresh_age_seconds": last_refresh_age_seconds(config_dir),
    }


# Load previous limits.json (if any) so that on error we can fall back to
# last-known-good values with a `stale: true` flag. This way, a transient
# refresh/network blip doesn't blank the dashboard — it just shows "as of
# N minutes ago." The alerter still fires on sustained `error` entries,
# so we don't paper over real outages.
prev = {}
if os.path.isfile(OUTPUT):
    try:
        with open(OUTPUT) as f:
            prev = json.load(f)
    except Exception:
        prev = {}

result = {}
for acct in ("1", "2", "3"):
    fresh = fetch_one(acct)
    if "error" in fresh:
        prev_entry = prev.get(acct) if isinstance(prev, dict) else None
        if isinstance(prev_entry, dict) and "data" in prev_entry:
            # Keep the old data visible but mark it stale and record the
            # current error so the dashboard + alerter can both see it.
            result[acct] = {
                **prev_entry,
                "stale": True,
                "stale_since": prev_entry.get("stale_since") or prev_entry.get("fetched_at"),
                "last_error": fresh["error"],
                "error_at": datetime.now().isoformat(),
                # NOTE: keep top-level `error` set so alert-claude-limits.sh
                # still escalates sustained failures (it keys off `error`).
                "error": fresh["error"],
                # Overwrite with the CURRENT refresh-stamp age — spread of
                # prev_entry would otherwise preserve the stale snapshot,
                # which is exactly the signal we want fresh for alerting.
                "last_refresh_age_seconds": fresh.get("last_refresh_age_seconds"),
            }
        else:
            result[acct] = fresh
    else:
        result[acct] = fresh

# Atomic write of the limits file so readers (the dashboard API) never
# see a half-written JSON document.
tmp_out = OUTPUT + ".tmp"
with open(tmp_out, "w") as f:
    json.dump(result, f)
os.replace(tmp_out, OUTPUT)
try:
    os.chmod(OUTPUT, 0o666)
except Exception:
    pass

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Limits written to {OUTPUT}")
PYEOF
