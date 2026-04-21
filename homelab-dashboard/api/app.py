import json
import os
import subprocess
import uuid
import tempfile
from datetime import datetime, timezone
import urllib.request
from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Helpers ────────────────────────────────────────────────────────────

def run(cmd):
    return subprocess.check_output(cmd, text=True)

def iso_to_age_label(iso_str):
    try:
        t = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - t
        sec = int(delta.total_seconds())
        if sec < 60:   return f"{sec}s ago"
        if sec < 3600: return f"{sec//60}m ago"
        if sec < 86400:return f"{sec//3600}h ago"
        return f"{sec//86400}d ago"
    except Exception:
        return iso_str

def find_nextcloud_data_dir():
    env = os.environ.get("NEXTCLOUD_DATA_DIR")
    if env and os.path.isdir(env):
        return env
    for p in ["/var/www/nextcloud/data", "/srv/nextcloud/data",
              "/mnt/nextcloud/data", "/var/snap/nextcloud/common/nextcloud/data"]:
        if os.path.isdir(p):
            return p
    return None

def human(n: float) -> str:
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if n < 1024: return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}EB"

def glances_fetch(base, path):
    raw = urllib.request.urlopen(f"{base}/api/4/{path}", timeout=5).read()
    return json.loads(raw)

HA_URL   = os.environ.get("HA_URL", "http://localhost:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

def ha_get(path):
    req = urllib.request.Request(
        f"{HA_URL}/api/{path}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=4).read())

def ha_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{HA_URL}/api/{path}", data=data, method="POST",
        headers={"Authorization": f"Bearer {HA_TOKEN}",
                 "Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=4)

# ── Dashboard ──────────────────────────────────────────────────────────

@app.get("/")
def dashboard():
    return send_from_directory("/app", "dashboard.html")

# ── Glances proxy ──────────────────────────────────────────────────────

GLANCES_SERVERS = {
    "main":   "http://glances:61208",
    "backup": "http://100.90.102.52:61208",
}

@app.get("/api/glances/<server>")
def glances(server):
    if server not in GLANCES_SERVERS:
        return jsonify({"error": "unknown server"}), 404
    base = GLANCES_SERVERS[server]
    try:
        ql  = glances_fetch(base, "quicklook")
        up  = glances_fetch(base, "uptime")
        try:
            fs_list = glances_fetch(base, "fs")
            root = next((f for f in fs_list if (f.get("mnt_point") or f.get("mountpoint")) == "/"), None)
            if root:
                disk_used  = root.get("used", 0)
                disk_total = root.get("size") or root.get("total") or 1
                disk_pct   = round(disk_used / disk_total * 100)
            else:
                disk_pct = None
        except Exception:
            disk_pct = None
        try:
            sensors = glances_fetch(base, "sensors")
            temps = [s for s in sensors
                     if isinstance(s.get("value"), (int, float))
                     and ("core" in s.get("label","").lower()
                          or "cpu"  in s.get("label","").lower()
                          or "temp" in s.get("label","").lower())]
            temp = round(sum(s["value"] for s in temps) / len(temps)) if temps else None
        except Exception:
            temp = None
        return jsonify({
            "cpu":    round(ql.get("cpu",  0)),
            "mem":    round(ql.get("mem",  0)),
            "swap":   round(ql.get("swap", 0)),
            "disk":   disk_pct,
            "uptime": up if isinstance(up, str) else str(up),
            "temp":   temp,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502

# ── Tailscale ──────────────────────────────────────────────────────────

@app.get("/api/tailscale/peers")
def tailscale_peers():
    try:
        raw   = run(["tailscale", "status", "--json"])
        data  = json.loads(raw)
        peers = data.get("Peer", {}) or {}
        items = []
        for _k, p in peers.items():
            name = (p.get("HostName") or p.get("DNSName") or "unknown")
            name = name.replace(".tailb8843e.ts.net", "").rstrip(".")
            ip   = (p.get("TailscaleIPs") or [""])[0]
            online    = bool(p.get("Online", False))
            last_seen = p.get("LastSeen")
            items.append({
                "name":      name,
                "ip":        ip,
                "online":    online,
                "last_seen": iso_to_age_label(last_seen) if last_seen and not online else None,
            })
        items.sort(key=lambda x: (0 if x["online"] else 1, x["name"].lower()))
        return jsonify({"peers": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Backup status ──────────────────────────────────────────────────────

@app.get("/api/backup/status")
def backup_status():
    try:
        raw = urllib.request.urlopen(
            "http://100.90.102.52:8081/backup-last.json", timeout=5
        ).read().decode()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.get("/api/backup/live")
def backup_live():
    try:
        raw = urllib.request.urlopen(
            "http://100.90.102.52:8081/backup-live.json", timeout=5
        ).read().decode()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"inProgress": False})

@app.get("/api/backup/running")
def backup_running_status():
    try:
        raw = urllib.request.urlopen(
            "http://100.90.102.52:8081/backup-status", timeout=5
        ).read().decode()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"running": False, "error": str(e)})

@app.post("/api/backup/trigger")
def backup_trigger():
    try:
        req = urllib.request.Request(
            "http://100.90.102.52:8081/run-backup",
            data=b'{}', method="POST",
            headers={"Content-Type": "application/json"}
        )
        raw = urllib.request.urlopen(req, timeout=10).read().decode()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

# ── Home Assistant ─────────────────────────────────────────────────────

SKIP_DOMAINS = {
    "persistent_notification","tts","zone","sun","weather","update",
    "conversation","stt","wake_word","assist_pipeline","scene",
    "automation","script",
}

@app.get("/api/ha/devices")
def ha_devices():
    try:
        states = ha_get("states")
        result = {}
        for s in states:
            domain = s["entity_id"].split(".")[0]
            if domain in SKIP_DOMAINS:
                continue
            attrs = s.get("attributes", {})
            b = attrs.get("brightness")
            result.setdefault(domain, []).append({
                "entity_id":      s["entity_id"],
                "name":           attrs.get("friendly_name", s["entity_id"]),
                "state":          s["state"],
                "brightness_pct": round(b / 255 * 100) if b else None,
                "unit":           attrs.get("unit_of_measurement"),
                "device_class":   attrs.get("device_class"),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/ha/control")
def ha_control():
    try:
        body      = request.get_json() or {}
        entity_id = body["entity_id"]
        action    = body["action"]
        extra     = body.get("data", {})
        domain    = entity_id.split(".")[0]
        ha_post(f"services/{domain}/{action}", {"entity_id": entity_id, **extra})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Legacy endpoints (kept for Homepage compatibility) ─────────────────

@app.get("/api/tailscale-text")
def tailscale_text():
    try:
        raw   = run(["tailscale", "status", "--json"])
        data  = json.loads(raw)
        peers = data.get("Peer", {}) or {}
        items = []
        for _k, p in peers.items():
            name   = p.get("HostName") or p.get("DNSName") or "unknown"
            ip     = (p.get("TailscaleIPs") or [""])[0]
            online = bool(p.get("Online", False))
            last   = p.get("LastSeen")
            status = "ONLINE" if online else f"OFFLINE ({iso_to_age_label(last) if last else 'n/a'})"
            items.append((0 if online else 1, name.lower(), name, ip, status))
        items.sort()
        return jsonify({"text": "\n".join(f"- {n} — {ip} — {s}" for _,__,n,ip,s in items)})
    except Exception as e:
        return jsonify({"text": f"- tailscale error: {type(e).__name__}"})

@app.get("/api/nextcloud-disk-fields")
def nextcloud_disk_fields():
    p = find_nextcloud_data_dir()
    if not p:
        return jsonify({"path":"(not found)","total":"n/a","used":"n/a","free":"n/a","pct":"n/a"})
    st    = os.statvfs(p)
    total = st.f_frsize * st.f_blocks
    free  = st.f_frsize * st.f_bavail
    used  = total - free
    pct   = (used / total * 100) if total else 0
    return jsonify({"path":p,"total":human(total),"used":human(used),"free":human(free),"pct":f"{pct:.1f}%"})

@app.get("/api/backup-disk-fields")
def backup_disk_fields():
    try:
        raw  = urllib.request.urlopen("http://100.90.102.52:61208/api/4/fs", timeout=4).read().decode()
        data = json.loads(raw)
        if not isinstance(data, list) or not data:
            return jsonify({"path":"(no data)","total":"n/a","used":"n/a","free":"n/a","pct":"n/a"})
        def mp(it):  return it.get("mnt_point") or it.get("mountpoint") or it.get("path")
        def tot(it): return float(it.get("size") or it.get("total") or 0)
        def usd(it): return float(it.get("used") or 0)
        def fre(it): return float(it.get("free") or (tot(it) - usd(it)))
        def pct(it):
            v = it.get("percent")
            return float(v) if v is not None else (usd(it)/tot(it)*100 if tot(it) else 0)
        root = next((i for i in data if mp(i) == "/"), None) or max(data, key=tot)
        return jsonify({"path":mp(root) or "/","total":human(tot(root)),"used":human(usd(root)),
                        "free":human(fre(root)),"pct":f"{pct(root):.1f}%"})
    except Exception as e:
        return jsonify({"path":"(error)","total":"n/a","used":"n/a","free":"n/a","pct":type(e).__name__})

@app.get("/api/ha/summary")
def ha_summary():
    try:
        states      = ha_get("states")
        lights_on   = sum(1 for s in states if s["entity_id"].startswith("light.") and s["state"] == "on")
        lights_total= sum(1 for s in states if s["entity_id"].startswith("light."))
        return jsonify({"lights": f"{lights_on}/{lights_total} on", "total_entities": len(states)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Claude Ideas ───────────────────────────────────────────────────────

CLAUDE_IDEAS_FILE = os.environ.get("CLAUDE_IDEAS_FILE", "/opt/claude-ideas/project-ideas.txt")
CLAUDE_LOG_FILE   = os.environ.get("CLAUDE_LOG_FILE",   "/opt/claude-ideas/generator.log")
CLAUDE_ACCOUNTS   = [1, 2, 3]
# Config dirs for each account — used to run `claude /usage`
CLAUDE_CONFIG_DIRS = {
    1: "/home/luis/.claude-account-1",
    2: "/home/luis/.claude-account-2",
    3: "/home/luis/.claude-account-3",
}

def read_claude_account(config_dir: str) -> dict:
    """Read account info directly from .claude.json — no subprocess needed."""
    claude_json = os.path.join(config_dir, ".claude.json")
    if not os.path.isfile(claude_json):
        return {"error": "not logged in"}
    try:
        with open(claude_json) as f:
            data = json.load(f)

        acct = data.get("oauthAccount", {})
        billing = acct.get("billingType", "")
        plan = "Max" if "max" in billing.lower() else \
               "Pro" if "pro" in billing.lower() else \
               billing.replace("_", " ").title() if billing else "Unknown"

        # Aggregate cost & tokens across all projects
        total_cost   = 0.0
        total_input  = 0
        total_output = 0
        total_cache  = 0
        projects = data.get("projects", {})
        for proj in projects.values():
            total_cost   += proj.get("lastCost", 0)
            total_input  += proj.get("lastTotalInputTokens", 0)
            total_output += proj.get("lastTotalOutputTokens", 0)
            total_cache  += proj.get("lastTotalCacheReadInputTokens", 0)
            # also accumulate from lastModelUsage if present
            for model_data in proj.get("lastModelUsage", {}).values():
                total_cost += model_data.get("costUSD", 0)

        extra_usage = acct.get("hasExtraUsageEnabled", False)
        first_token = data.get("claudeCodeFirstTokenDate", "")[:10] if data.get("claudeCodeFirstTokenDate") else "—"

        return {
            "email":        acct.get("emailAddress", "—"),
            "display_name": acct.get("displayName", "—"),
            "plan":         plan,
            "extra_usage":  extra_usage,
            "member_since": first_token,
            "total_cost_usd": round(total_cost, 4),
            "total_input_tokens":  total_input,
            "total_output_tokens": total_output,
            "total_cache_tokens":  total_cache,
            "project_count": len(projects),
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/claude/usage")
def claude_usage():
    results = {}
    for acct in CLAUDE_ACCOUNTS:
        config_dir = CLAUDE_CONFIG_DIRS[acct]
        results[str(acct)] = read_claude_account(config_dir)
    return jsonify(results)

CLAUDE_LIMITS_FILE = os.environ.get("CLAUDE_LIMITS_FILE", "/opt/claude-ideas/limits.json")

def fmt_resets(iso: str) -> str:
    """Convert ISO timestamp to human-readable 'resets in Xh Ym' or 'resets Mon 3:00 PM'."""
    if not iso:
        return ""
    try:
        from datetime import timezone
        t = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc)
        diff = (t - now).total_seconds()
        if diff <= 0:
            return "resetting soon"
        d = int(diff // 86400)
        h = int((diff % 86400) // 3600)
        m = int((diff % 3600) // 60)
        if d > 0:
            return f"resets in {d}d {h}h"
        if h > 0:
            return f"resets in {h}h {m}m"
        return f"resets in {m}m"
    except Exception:
        return ""

FETCH_LIMITS_SCRIPT = os.environ.get(
    "FETCH_LIMITS_SCRIPT",
    "/opt/homelab/scripts/claude-ideas/fetch-claude-limits.sh"
)

def _get_valid_token(creds_path: str) -> str:
    """Return a valid access token, refreshing it first if expired or close to expiry."""
    with open(creds_path) as f:
        creds = json.load(f)
    oauth = creds.get("claudeAiOauth", {})
    access_token  = oauth.get("accessToken", "")
    refresh_token = oauth.get("refreshToken", "")
    expires_at    = oauth.get("expiresAt", 0)  # milliseconds epoch

    # Refresh if expired or expiring within the next 60 seconds
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    if access_token and expires_at and (expires_at - now_ms) > 60_000:
        return access_token  # still valid

    if not refresh_token:
        return access_token  # nothing we can do, use what we have

    # Call the OAuth token refresh endpoint
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(
        "https://auth.anthropic.com/oauth/token",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        raw = urllib.request.urlopen(req, timeout=10).read()
        new_tokens = json.loads(raw)
        new_access  = new_tokens.get("access_token", "")
        new_refresh = new_tokens.get("refresh_token", refresh_token)
        new_expires = new_tokens.get("expires_in")  # seconds from now

        if new_access:
            # Persist refreshed tokens back to the credentials file
            oauth["accessToken"]  = new_access
            oauth["refreshToken"] = new_refresh
            if new_expires:
                oauth["expiresAt"] = int((datetime.now(timezone.utc).timestamp() + new_expires) * 1000)
            creds["claudeAiOauth"] = oauth
            try:
                with open(creds_path, "w") as f:
                    json.dump(creds, f, indent=2)
            except Exception:
                pass  # read-only mount — use token anyway
            return new_access
    except Exception:
        pass  # refresh failed — fall back to existing token

    return access_token

def _fetch_account_limits(acct: int) -> dict:
    """Fetch session + weekly usage limits from Anthropic API for one account."""
    config_dir = CLAUDE_CONFIG_DIRS[acct]
    creds_path = os.path.join(config_dir, ".credentials.json")
    if not os.path.isfile(creds_path):
        return {"error": "no credentials"}
    try:
        token = _get_valid_token(creds_path)
        if not token:
            return {"error": "no token"}
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "claude-code",
                "anthropic-beta": "oauth-2025-04-20",
            }
        )
        raw = urllib.request.urlopen(req, timeout=10).read()
        return {"data": json.loads(raw), "fetched_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/claude/refresh-limits")
def refresh_limits():
    """Fetch fresh token limit data from Anthropic API and write to limits.json."""
    try:
        result = {}
        for acct in CLAUDE_ACCOUNTS:
            result[str(acct)] = _fetch_account_limits(acct)
        os.makedirs(os.path.dirname(CLAUDE_LIMITS_FILE), exist_ok=True)
        with open(CLAUDE_LIMITS_FILE, "w") as f:
            json.dump(result, f)
        os.chmod(CLAUDE_LIMITS_FILE, 0o666)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/claude/limits")
def claude_limits():
    """Read and parse limits from file written by fetch-claude-limits.sh on the host."""
    try:
        if not os.path.isfile(CLAUDE_LIMITS_FILE):
            return jsonify({"error": "limits file not found — run fetch-claude-limits.sh on host"})
        with open(CLAUDE_LIMITS_FILE) as f:
            raw = json.load(f)

        result = {}
        for acct, entry in raw.items():
            if "error" in entry:
                result[acct] = {"error": entry["error"]}
                continue
            d = entry.get("data", {})
            five  = d.get("five_hour") or {}
            seven = d.get("seven_day") or {}
            result[acct] = {
                "fetched_at": entry.get("fetched_at"),
                "session": {
                    "pct":      round(float(five.get("utilization", 0))),
                    "resets":   fmt_resets(five.get("resets_at", "")),
                },
                "weekly": {
                    "pct":    round(float(seven.get("utilization", 0))),
                    "resets": fmt_resets(seven.get("resets_at", "")),
                },
            }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.get("/api/claude/log-stats")
def claude_log_stats():
    """Parse generator.log to get per-account run stats."""
    stats = {str(i): {"runs": 0, "errors": 0, "last_run": None, "last_status": None}
             for i in CLAUDE_ACCOUNTS}
    try:
        if not os.path.exists(CLAUDE_LOG_FILE):
            return jsonify({"error": "log not found", "accounts": stats})
        with open(CLAUDE_LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                # Format: [2026-04-15 04:00:01] Account 1 - Starting idea generation...
                # or:     [2026-04-15 04:00:22] Account 1 - Done. Output appended to ...
                # or:     [2026-04-15 04:00:22] Account 1 - ERROR: ...
                import re
                m = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] Account (\d) - (.+)', line)
                if not m:
                    continue
                ts, acct, msg = m.group(1), m.group(2), m.group(3)
                if acct not in stats:
                    continue
                if "ERROR" in msg:
                    stats[acct]["errors"] += 1
                    stats[acct]["last_run"] = ts
                    stats[acct]["last_status"] = "error"
                elif "Done" in msg:
                    stats[acct]["runs"] += 1
                    stats[acct]["last_run"] = ts
                    stats[acct]["last_status"] = "ok"
        return jsonify({"accounts": stats})
    except Exception as e:
        return jsonify({"error": str(e), "accounts": stats})

CLAUDE_GRAVEYARD_FILE = os.environ.get("CLAUDE_GRAVEYARD_FILE", "/opt/claude-ideas/graveyard.jsonl")

def _append_graveyard(idea: dict):
    """Save a deleted idea's concept to the graveyard so the generator avoids repeating it."""
    try:
        record = {
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "name":       idea.get("name", ""),
            "tagline":    idea.get("tagline", ""),
            "tags":       idea.get("tags", []),
        }
        with open(CLAUDE_GRAVEYARD_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        os.chmod(CLAUDE_GRAVEYARD_FILE, 0o666)
    except Exception:
        pass  # non-fatal

@app.delete("/api/claude/ideas/<int:line_index>")
def delete_claude_idea(line_index):
    """Delete idea at the given 0-based line index (as shown in the dashboard, reversed)."""
    jsonl_path = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")
    if not os.path.exists(jsonl_path):
        return jsonify({"error": "ideas file not found"}), 404
    try:
        with open(jsonl_path) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        # Dashboard shows newest first (reversed), so line_index 0 = last line in file
        reversed_lines = list(reversed(lines))
        if line_index < 0 or line_index >= len(reversed_lines):
            return jsonify({"error": "index out of range"}), 400
        deleted_line = reversed_lines.pop(line_index)
        # Save deleted idea to graveyard
        try:
            _append_graveyard(json.loads(deleted_line))
        except Exception:
            pass
        new_lines = list(reversed(reversed_lines))
        with open(jsonl_path, "w") as f:
            f.write("\n".join(new_lines) + ("\n" if new_lines else ""))
        return jsonify({"ok": True, "remaining": len(new_lines)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/claude/ideas")
def claude_ideas():
    """Return parsed idea entries from the ideas file (JSON lines or legacy text)."""
    import re
    ideas_file = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl") \
        if os.path.exists(CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")) \
        else CLAUDE_IDEAS_FILE
    try:
        if not os.path.exists(ideas_file) and not os.path.exists(CLAUDE_IDEAS_FILE):
            return jsonify({"error": "ideas file not found", "ideas": []})

        # Try JSONL first (new format)
        jsonl_path = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")
        if os.path.exists(jsonl_path):
            ideas = []
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            ideas.append(json.loads(line))
                        except Exception:
                            pass
            ideas.reverse()
            return jsonify({"total": len(ideas), "ideas": ideas[:100]})

        # Fallback: parse legacy plain text file
        with open(CLAUDE_IDEAS_FILE) as f:
            content = f.read()
        entries = re.split(r'={40,}', content)
        ideas = []
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            header = re.search(
                r'Generated:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*Account:\s*(\d)',
                entry
            )
            if header:
                ts   = header.group(1)
                acct = header.group(2)
                body = re.sub(r'Generated:.*\|.*Account:.*\d', '', entry).strip()
            else:
                ts, acct, body = None, None, entry
            if body:
                ideas.append({"generated_at": ts, "account": acct, "content": body})
        ideas.reverse()
        return jsonify({"total": len(ideas), "ideas": ideas[:100]})
    except Exception as e:
        return jsonify({"error": str(e), "ideas": []})

# ── Claude Builds ──────────────────────────────────────────────────────

BUILDS_DIR        = "/opt/claude-ideas/builds"
BUILD_RUNNER      = "/home/luis/scripts/claude-ideas/run-build.sh"
VALID_MODELS      = {"haiku", "sonnet", "opus",
                     "claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5",
                     "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250514",
                     "claude-opus-4-5-20250514"}
VALID_ACCOUNTS    = {1, 2, 3}

def _build_status(build_id: str) -> dict:
    path = os.path.join(BUILDS_DIR, f"{build_id}.json")
    if not os.path.isfile(path):
        return {"error": "build not found"}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/claude/build")
def start_build():
    """Enqueue a Claude Code build job by writing a job file for the host watcher to pick up."""
    try:
        body         = request.get_json() or {}
        prompt       = (body.get("prompt") or "").strip()
        account      = int(body.get("account", 1))
        model        = (body.get("model") or "claude-sonnet-4-5").strip()
        project_name = (body.get("project_name") or "project").strip()

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400
        if account not in VALID_ACCOUNTS:
            return jsonify({"error": "account must be 1, 2, or 3"}), 400

        # Normalise short model aliases
        model_map = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-4-5", "opus": "claude-opus-4-5"}
        model = model_map.get(model, model)

        build_id = str(uuid.uuid4())[:8]
        slug     = "".join(c if c.isalnum() or c == "-" else "-" for c in project_name.lower()).strip("-")[:48] or "project"

        os.makedirs(BUILDS_DIR, exist_ok=True)

        # Write the prompt file
        prompt_path = os.path.join(BUILDS_DIR, f"{build_id}.prompt.txt")
        with open(prompt_path, "w") as f:
            f.write(prompt)
        os.chmod(prompt_path, 0o666)

        # Write the job file — the host-side build-watcher.sh picks this up
        job = {
            "build_id":    build_id,
            "account":     account,
            "model":       model,
            "slug":        slug,
            "prompt_file": prompt_path,
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }
        job_path = os.path.join(BUILDS_DIR, f"{build_id}.job.json")
        with open(job_path, "w") as f:
            json.dump(job, f)

        # Write initial status so polling has something to read immediately
        status = {
            "build_id":     build_id,
            "account":      account,
            "model":        model,
            "project_slug": slug,
            "status":       "queued",
            "message":      "Waiting for build runner…",
            "started_at":   datetime.now(timezone.utc).isoformat(),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
            "project_dir":  f"/home/luis/claude-builds/{slug}",
            "zip_path":     os.path.join(BUILDS_DIR, f"{build_id}.zip"),
        }
        status_path = os.path.join(BUILDS_DIR, f"{build_id}.json")
        with open(status_path, "w") as f:
            json.dump(status, f)
        # Make world-writable so run-build.sh (running as luis) can overwrite it
        os.chmod(status_path, 0o666)

        return jsonify({"ok": True, "build_id": build_id, "slug": slug, "model": model, "account": account})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/claude/build/<build_id>")
def get_build_status(build_id):
    """Poll build status."""
    # Sanitise — only allow hex + hyphens
    safe = "".join(c for c in build_id if c.isalnum() or c == "-")[:36]
    return jsonify(_build_status(safe))

@app.get("/api/claude/build/<build_id>/log")
def get_build_log(build_id):
    """Return the tail of the build log."""
    safe = "".join(c for c in build_id if c.isalnum() or c == "-")[:36]
    log_path = os.path.join(BUILDS_DIR, f"{safe}.log")
    if not os.path.isfile(log_path):
        return jsonify({"log": ""}), 200
    try:
        with open(log_path) as f:
            lines = f.readlines()
        return jsonify({"log": "".join(lines[-80:])})  # last 80 lines
    except Exception as e:
        return jsonify({"log": f"Error reading log: {e}"}), 200

@app.get("/api/claude/build/<build_id>/zip")
def download_build_zip(build_id):
    """Stream the completed zip back to the browser."""
    safe = "".join(c for c in build_id if c.isalnum() or c == "-")[:36]
    status = _build_status(safe)
    if "error" in status:
        return jsonify(status), 404
    if status.get("status") != "done":
        return jsonify({"error": "build not finished yet"}), 409
    zip_path = os.path.join(BUILDS_DIR, f"{safe}.zip")
    if not os.path.isfile(zip_path):
        return jsonify({"error": "zip file not found"}), 404
    slug = status.get("project_slug", safe)
    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{slug}.zip",
    )

CLAUDE_BUILDS_DIR = os.environ.get("CLAUDE_BUILDS_DIR", "/home/luis/claude-builds")

@app.get("/api/claude/builds")
def list_builds():
    """List all built project directories with metadata."""
    try:
        if not os.path.isdir(CLAUDE_BUILDS_DIR):
            return jsonify({"builds": []})
        entries = []
        for name in sorted(os.listdir(CLAUDE_BUILDS_DIR)):
            path = os.path.join(CLAUDE_BUILDS_DIR, name)
            if not os.path.isdir(path):
                continue
            stat = os.stat(path)
            # Get size via du
            try:
                size_out = subprocess.check_output(
                    ["du", "-sh", path], text=True, stderr=subprocess.DEVNULL
                )
                size = size_out.split()[0]
            except Exception:
                size = "?"
            # Find matching build id from builds dir json files
            build_id = None
            zip_exists = False
            for fname in os.listdir(BUILDS_DIR):
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(BUILDS_DIR, fname)) as f:
                        d = json.load(f)
                    if d.get("project_slug") == name and d.get("status") == "done":
                        build_id = d.get("build_id")
                        zip_path = os.path.join(BUILDS_DIR, f"{build_id}.zip")
                        zip_exists = os.path.isfile(zip_path)
                        break
                except Exception:
                    continue
            entries.append({
                "slug":       name,
                "size":       size,
                "modified":   int(stat.st_mtime),
                "build_id":   build_id,
                "zip_exists": zip_exists,
            })
        # Newest first
        entries.sort(key=lambda x: x["modified"], reverse=True)
        return jsonify({"builds": entries})
    except Exception as e:
        return jsonify({"error": str(e), "builds": []}), 500

def _delete_build_dir(safe: str):
    """Delete a built project dir and its build artifacts. Returns (ok, error)."""
    import shutil
    path = os.path.join(CLAUDE_BUILDS_DIR, safe)
    if not os.path.isdir(path):
        return False, "not found"
    shutil.rmtree(path)
    # Also write slug to graveyard so the generator avoids repeating it
    _append_graveyard({"name": safe.replace("-", " ").title(), "tagline": "", "tags": []})
    # Clean up build artifacts
    for fname in list(os.listdir(BUILDS_DIR)):
        fpath = os.path.join(BUILDS_DIR, fname)
        try:
            with open(fpath) as f:
                d = json.load(f)
            if d.get("project_slug") == safe:
                os.remove(fpath)
        except Exception:
            pass
    return True, None

@app.delete("/api/claude/builds/<slug>")
def delete_build(slug):
    """Delete a built project directory."""
    safe = "".join(c for c in slug if c.isalnum() or c == "-")[:64]
    if not safe:
        return jsonify({"error": "invalid slug"}), 400
    ok, err = _delete_build_dir(safe)
    if not ok:
        return jsonify({"error": err}), 404
    return jsonify({"ok": True})

@app.delete("/api/claude/builds")
def wipe_all_builds():
    """Delete all built project directories."""
    if not os.path.isdir(CLAUDE_BUILDS_DIR):
        return jsonify({"ok": True, "deleted": 0})
    deleted = 0
    errors = []
    for name in os.listdir(CLAUDE_BUILDS_DIR):
        path = os.path.join(CLAUDE_BUILDS_DIR, name)
        if not os.path.isdir(path):
            continue
        ok, err = _delete_build_dir(name)
        if ok:
            deleted += 1
        else:
            errors.append(f"{name}: {err}")
    if errors:
        return jsonify({"ok": False, "deleted": deleted, "errors": errors}), 500
    return jsonify({"ok": True, "deleted": deleted})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787)
