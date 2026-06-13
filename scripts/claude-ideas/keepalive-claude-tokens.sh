#!/bin/bash
# ============================================================
# Daily keep-alive: forces an OAuth refresh_token rotation for
# every Claude account, even if the cached access_token is still
# valid. This prevents refresh_tokens from expiring due to
# inactivity (which is what bricked accounts 2 and 3 after the
# 2026-04-21 power outage).
#
# Uses the same flock + atomic-write protocol as fetch-claude-limits.sh.
# Only one writer per .credentials.json at a time.
#
# Add to crontab to run once per day (offset from the hourly fetcher
# so they don't collide):
#   17 3 * * * /opt/homelab/scripts/claude-ideas/keepalive-claude-tokens.sh
# ============================================================

LOG="/opt/claude-ideas/keepalive.log"
mkdir -p /opt/claude-ideas

CLAUDE_HOME="${CLAUDE_HOME:-$HOME}"

python3 - "$CLAUDE_HOME" "$LOG" <<'PYEOF'
import json
import os
import sys
import fcntl
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

HOME = sys.argv[1]
LOG  = sys.argv[2]

# OAuth token endpoint moved from auth.anthropic.com to platform.claude.com
# in early 2026. The old hostname no longer resolves (NXDOMAIN), which is
# what broke this script's first run. Source of truth: TOKEN_URL constant
# in the bundled Claude Code CLI (/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js).
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"

# Claude Code's public OAuth client_id. The /v1/oauth/token endpoint returns
# 400 "Invalid request format" when the refresh_token grant is posted without
# it — confirmed empirically 2026-04-24. Source of truth: CLIENT_ID constant
# in the bundled @anthropic-ai/claude-code cli.js.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def force_refresh(creds_path):
    """Unconditionally swap refresh_token for a fresh access_token,
    even if the current access_token isn't close to expiring.
    Holds an exclusive lock on the creds file end-to-end."""
    with open(creds_path, "r+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            creds = json.load(fh)
            oauth = creds.get("claudeAiOauth", {})
            refresh_token = oauth.get("refreshToken", "")
            if not refresh_token:
                return "no refresh token on disk"

            payload = json.dumps({
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            })

            # Shell out to curl: Cloudflare in front of platform.claude.com
            # does TLS-fingerprint-based bot detection (error 1010) that
            # blocks Python's urllib regardless of HTTP headers — it's the
            # OpenSSL ClientHello being flagged, not the User-Agent. curl's
            # TLS fingerprint passes. System curl avoids adding curl_cffi /
            # httpx-impersonation as a dep on the host. --fail-with-body
            # gives nonzero exit on 4xx/5xx while still returning the body,
            # so a bricked refresh token surfaces as invalid_grant rather
            # than a bare HTTP status.
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
                return f"refresh request failed: subprocess error: {e}"

            if result.returncode != 0:
                body = result.stdout.decode(errors="replace")[:500]
                err  = result.stderr.decode(errors="replace")[:200]
                return f"refresh request failed: curl exit {result.returncode}: {body} | {err}"

            raw = result.stdout

            new_tokens = json.loads(raw)
            new_access  = new_tokens.get("access_token", "")
            new_refresh = new_tokens.get("refresh_token", refresh_token)
            new_expires = new_tokens.get("expires_in")

            if not new_access:
                return "refresh response had no access_token"

            oauth["accessToken"]  = new_access
            oauth["refreshToken"] = new_refresh
            if new_expires:
                oauth["expiresAt"] = int(
                    (datetime.now(timezone.utc).timestamp() + new_expires) * 1000
                )
            creds["claudeAiOauth"] = oauth

            tmp_path = creds_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(creds, f, indent=2)
            os.replace(tmp_path, creds_path)

            stamp_path = os.path.join(os.path.dirname(creds_path), ".last_refresh")
            with open(stamp_path, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())

            return "ok"
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


for acct in ("1", "2", "3"):
    creds_path = os.path.join(HOME, f".claude-account-{acct}", ".credentials.json")
    if not os.path.isfile(creds_path):
        log(f"account {acct}: no credentials file — skipping")
        continue
    try:
        result = force_refresh(creds_path)
    except Exception as e:
        result = f"unexpected error: {e}"
    log(f"account {acct}: {result}")
PYEOF
