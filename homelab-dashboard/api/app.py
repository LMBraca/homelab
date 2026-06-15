import json
import os
import subprocess
import time
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
    """Convert ISO timestamp to human-readable 'resets in Xh Ym' or 'reset Xh ago'."""
    if not iso:
        return ""
    try:
        from datetime import timezone
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (t - now).total_seconds()
        if diff <= 0:
            ago = -diff
            d = int(ago // 86400)
            h = int((ago % 86400) // 3600)
            m = int((ago % 3600) // 60)
            if d > 0:
                return f"reset {d}d {h}h ago"
            if h > 0:
                return f"reset {h}h {m}m ago"
            if m > 0:
                return f"reset {m}m ago"
            return "just reset"
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

# NOTE: app.py is intentionally READ-ONLY on the .credentials.json files
# (the docker-compose mount uses :ro). The host-side cron scripts
#   /opt/homelab/scripts/claude-ideas/fetch-claude-limits.sh
#   /opt/homelab/scripts/claude-ideas/keepalive-claude-tokens.sh
# are the ONLY writers of those files (and of /opt/claude-ideas/limits.json).
# This avoids a race where two processes refresh the same OAuth refresh_token
# concurrently, persist different rotations of it, and lock each other out
# with HTTP 401.
#
# The "Refresh now" button cannot shell out to fetch-claude-limits.sh from
# inside this container — the creds dir is mounted :ro, so any refresh
# attempt fails with EROFS. Instead, the dashboard drops a trigger file in
# the shared writable /opt/claude-ideas dir. A host-side systemd path unit
# watches for the trigger and invokes fetch-claude-limits.sh as `luis` (who
# can write creds). If no trigger-watcher is installed, the hourly cron
# keeps limits.json fresh on its own schedule.
REFRESH_TRIGGER_FILE = "/opt/claude-ideas/.refresh-requested"
# Minimum seconds between accepted refresh requests. Rapid clicks on the
# dashboard's "Refresh now" button previously fired the systemd path watcher
# 6+ times in a 7-second window and tripped its StartLimitBurst (default 5
# in 10s), after which the watcher refuses to run until the rate-limit
# window rolls. Process-local debounce; single-worker Flask deployment so
# this is race-safe enough for a homelab dashboard.
REFRESH_DEBOUNCE_SEC = 5
_last_refresh_queued_at = 0.0

@app.post("/api/claude/refresh-limits")
def refresh_limits():
    """Signal the host-side fetcher to refresh now.

    Writes a trigger file in the shared writable dir; a systemd path unit on
    the host picks it up and runs fetch-claude-limits.sh under the correct UID
    with read-write access to the creds files. If no watcher is installed,
    the hourly cron is still running and will refresh on its own cadence.
    """
    global _last_refresh_queued_at
    now = time.monotonic()
    if now - _last_refresh_queued_at < REFRESH_DEBOUNCE_SEC:
        return jsonify({
            "ok": True,
            "queued": True,
            "debounced": True,
            "note": f"Another refresh was queued {now - _last_refresh_queued_at:.1f}s "
                    f"ago; coalescing (min interval {REFRESH_DEBOUNCE_SEC}s).",
        })
    try:
        os.makedirs(os.path.dirname(REFRESH_TRIGGER_FILE), exist_ok=True)
        # Atomic create-or-touch so multiple rapid clicks coalesce into one
        # refresh (the watcher consumes + deletes the trigger).
        with open(REFRESH_TRIGGER_FILE, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat() + "\n")
        _last_refresh_queued_at = now
        return jsonify({
            "ok": True,
            "queued": True,
            "note": "Refresh requested. Host-side fetcher will run within a few seconds "
                    "(or on the next hourly cron tick if no path watcher is installed).",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"could not queue refresh: {e}"}), 500

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
            # Graceful degradation: if fetch-claude-limits.sh preserved
            # stale `data` alongside an error (its standard behavior on
            # refresh failure), render the bars from the stale data and
            # surface the error/stale metadata alongside — rather than
            # collapsing to "limits unavailable" and discarding usable
            # values. The 2026-04-22..24 outage showed that short-circuit
            # hiding the fact that everything had been stale for hours.
            d = entry.get("data")
            if isinstance(d, dict):
                five  = d.get("five_hour") or {}
                seven = d.get("seven_day") or {}
                out = {
                    "fetched_at": entry.get("fetched_at"),
                    "session": {
                        "pct":    round(float(five.get("utilization", 0))),
                        "resets": fmt_resets(five.get("resets_at", "")),
                    },
                    "weekly": {
                        "pct":    round(float(seven.get("utilization", 0))),
                        "resets": fmt_resets(seven.get("resets_at", "")),
                    },
                }
                if entry.get("stale"):
                    out["stale"] = True
                    out["stale_since"] = entry.get("stale_since")
                if "error" in entry:
                    out["error"] = entry["error"]
                if entry.get("last_refresh_age_seconds") is not None:
                    out["last_refresh_age_seconds"] = entry["last_refresh_age_seconds"]
                result[acct] = out
            else:
                # No usable data at all — genuine "nothing to show" state.
                out = {"error": entry.get("error", "no data")}
                if entry.get("last_refresh_age_seconds") is not None:
                    out["last_refresh_age_seconds"] = entry["last_refresh_age_seconds"]
                result[acct] = out
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.get("/api/claude/log-stats")
def claude_log_stats():
    """Parse generator.log to get per-account run stats + generator health.

    Health is derived from the most recent of (a) the last log line and
    (b) the last entry in project-ideas.jsonl for that account. The log can
    lag the JSONL when a run succeeded but its "Done" line was rotated/truncated,
    so trusting only the log can mark an account stalled while fresh ideas exist.

    Health states:
      ok      — last activity succeeded AND landed within STALL_HOURS
      error   — last log line was an error AND no newer JSONL entry exists
      stalled — no activity in STALL_HOURS (cron didn't fire, host was
                down, or the script crashed before writing anything)
    """
    import re
    # Cron cycle is 4.5h, BUT the per-account schedule has a 6h overnight gap
    # (e.g. Acct 1: 22:00 → 04:00). So 5h flagged everyone "stalled" every
    # night even when healthy. 8h covers the worst-case healthy gap (6h) plus
    # 2h slack — anything beyond means a run was genuinely missed.
    STALL_HOURS = _setting("dashboard", "stall_hours")
    stats = {str(i): {"runs": 0, "errors": 0, "last_run": None,
                      "last_status": None, "last_run_age_seconds": None,
                      "health": "stalled"}
             for i in CLAUDE_ACCOUNTS}
    try:
        if os.path.exists(CLAUDE_LOG_FILE):
            with open(CLAUDE_LOG_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    # Format: [2026-04-15 04:00:01] Account 1 - Starting idea generation...
                    # or:     [2026-04-15 04:00:22] Account 1 - Done. Output appended to ...
                    # or:     [2026-04-15 04:00:22] Account 1 - ERROR: ...
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

        # Cross-check against the JSONL ideas file. If an account has a newer
        # generated_at than its log shows, trust the JSONL (the run obviously
        # succeeded — an idea was appended).
        jsonl_path = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")
        if os.path.exists(jsonl_path):
            try:
                with open(jsonl_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        acct = str(rec.get("account", ""))
                        ts = rec.get("generated_at", "")
                        if acct not in stats or not ts:
                            continue
                        if not stats[acct]["last_run"] or ts > stats[acct]["last_run"]:
                            stats[acct]["last_run"] = ts
                            stats[acct]["last_status"] = "ok"
            except Exception:
                pass

        # Derive health + age from the latest run timestamp. Timestamps are
        # naive local time (writers use datetime.now() with no TZ), so compare
        # against datetime.now() — also naive local. Works as long as the host
        # TZ doesn't change between writes and reads.
        now = datetime.now()
        for acct, s in stats.items():
            if not s["last_run"]:
                s["health"] = "stalled"
                continue
            try:
                age = (now - datetime.strptime(s["last_run"], "%Y-%m-%d %H:%M:%S")).total_seconds()
                s["last_run_age_seconds"] = int(age)
            except Exception:
                s["last_run_age_seconds"] = None
                s["health"] = "stalled"
                continue
            if age > STALL_HOURS * 3600:
                s["health"] = "stalled"
            elif s["last_status"] == "error":
                s["health"] = "error"
            else:
                s["health"] = "ok"

        return jsonify({"accounts": stats, "stall_hours": STALL_HOURS})
    except Exception as e:
        return jsonify({"error": str(e), "accounts": stats})

CLAUDE_GRAVEYARD_FILE = os.environ.get("CLAUDE_GRAVEYARD_FILE", "/opt/claude-ideas/graveyard.jsonl")

def _idea_slug(name: str) -> str:
    """Canonical slug: same convention as start_build (alnum + hyphen, lowercase,
    capped at 48). Used to bridge idea.name ↔ ~/claude-builds/<slug>/ dirs."""
    if not name:
        return ""
    s = "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower()).strip("-")[:48]
    while "--" in s:
        s = s.replace("--", "-")
    return s

def _is_backup_dir(name: str) -> bool:
    """Built-project dirs that are stale rebuild backups created by run-build.sh
    (pattern: <slug>_backup_<epoch>). They live alongside live builds and shouldn't
    show up in either the ideas pool dedup or the builds table as primary entries."""
    return "_backup_" in name

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

@app.patch("/api/claude/ideas/<int:line_index>")
def edit_claude_idea(line_index):
    """Edit selected text fields on an idea in-place. Body accepts any subset of
    {build_prompt, tagline, name, problem}. Same reversed-index convention as
    the delete route (0 = newest)."""
    jsonl_path = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")
    if not os.path.exists(jsonl_path):
        return jsonify({"error": "ideas file not found"}), 404
    body = request.get_json(silent=True) or {}
    EDITABLE = ("build_prompt", "tagline", "name", "problem")
    updates = {k: body[k] for k in EDITABLE if k in body and isinstance(body[k], str)}
    if not updates:
        return jsonify({"error": "no editable fields supplied"}), 400
    try:
        with open(jsonl_path) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        reversed_lines = list(reversed(lines))
        if line_index < 0 or line_index >= len(reversed_lines):
            return jsonify({"error": "index out of range"}), 400
        try:
            record = json.loads(reversed_lines[line_index])
        except Exception as e:
            return jsonify({"error": f"corrupt record at index: {e}"}), 500
        record.update(updates)
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        reversed_lines[line_index] = json.dumps(record)
        new_lines = list(reversed(reversed_lines))
        with open(jsonl_path, "w") as f:
            f.write("\n".join(new_lines) + ("\n" if new_lines else ""))
        return jsonify({"ok": True, "idea": record})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/claude/ideas/bulk-delete")
def bulk_delete_claude_ideas():
    """Delete many ideas in one shot. Body: {"indices": [int, ...]}.
    Indices use the same dashboard convention as the single-delete route
    (0 = newest, matching the reversed render order)."""
    jsonl_path = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")
    if not os.path.exists(jsonl_path):
        return jsonify({"error": "ideas file not found"}), 404
    try:
        body = request.get_json(silent=True) or {}
        raw = body.get("indices") or []
        if not isinstance(raw, list) or not raw:
            return jsonify({"error": "indices must be a non-empty list"}), 400
        # Dedupe + validate
        indices = sorted({int(i) for i in raw if isinstance(i, int) or (isinstance(i, str) and i.isdigit())})
        with open(jsonl_path) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        reversed_lines = list(reversed(lines))
        if any(i < 0 or i >= len(reversed_lines) for i in indices):
            return jsonify({"error": "one or more indices out of range"}), 400
        # Remove from highest index first so positions stay valid
        deleted = 0
        for i in sorted(indices, reverse=True):
            line = reversed_lines.pop(i)
            try:
                _append_graveyard(json.loads(line))
            except Exception:
                pass
            deleted += 1
        new_lines = list(reversed(reversed_lines))
        with open(jsonl_path, "w") as f:
            f.write("\n".join(new_lines) + ("\n" if new_lines else ""))
        return jsonify({"ok": True, "deleted": deleted, "remaining": len(new_lines)})
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
            # Hide ideas whose project has already been built — they live on in
            # the "built projects" section with their full description.
            built_slugs = set()
            if os.path.isdir(CLAUDE_BUILDS_DIR):
                try:
                    for d in os.listdir(CLAUDE_BUILDS_DIR):
                        if os.path.isdir(os.path.join(CLAUDE_BUILDS_DIR, d)) and not _is_backup_dir(d):
                            built_slugs.add(d)
                except Exception:
                    pass
            ideas = [i for i in ideas if _idea_slug(i.get("name", "")) not in built_slugs]
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
                     "claude-haiku-4-5", "claude-sonnet-4-6",
                     "claude-opus-4-8", "claude-opus-4-7",
                     "claude-haiku-4-5-20251001"}
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
        model        = (body.get("model") or "claude-sonnet-4-6").strip()
        project_name = (body.get("project_name") or "project").strip()

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400
        if account not in VALID_ACCOUNTS:
            return jsonify({"error": "account must be 1, 2, or 3"}), 400

        # Normalise short model aliases
        model_map = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}
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

@app.post("/api/claude/build/<build_id>/cancel")
def cancel_build(build_id):
    """Stop an in-flight or stuck build and remove all of its files so the
    slug can be rebuilt cleanly. Drops a `.cancel` trigger file in
    BUILDS_DIR; the host-side build-watcher.sh picks it up, calls
    `systemctl --user stop claude-build-<id>.service` (killing the cgroup,
    so any leaked dev servers die with it), and rm's the status JSON, log,
    prompt, zip, job file, and ~/claude-builds/<slug>."""
    safe = "".join(c for c in build_id if c.isalnum() or c == "-")[:36]
    if not safe:
        return jsonify({"ok": False, "error": "invalid build_id"}), 400

    try:
        os.makedirs(BUILDS_DIR, exist_ok=True)
        cancel_path = os.path.join(BUILDS_DIR, f"{safe}.cancel")
        with open(cancel_path, "w") as f:
            f.write("")
        os.chmod(cancel_path, 0o666)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # Reflect the cancellation in the status file immediately so the
    # dashboard flips off "building" without waiting for the watcher tick.
    # The watcher will delete this file shortly as part of cleanup.
    status = _build_status(safe)
    if isinstance(status, dict) and "error" not in status:
        status["status"]     = "cancelling"
        status["message"]    = "Cancelling — stopping process and removing files…"
        status["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            with open(os.path.join(BUILDS_DIR, f"{safe}.json"), "w") as f:
                json.dump(status, f)
        except Exception:
            pass

    return jsonify({"ok": True, "build_id": safe})

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

@app.get("/api/claude/build-states")
def list_build_states():
    """Return the canonical build state for every project the server knows about,
    keyed by project slug. This is what every device reads — no localStorage —
    so a build queued/running/done on one device is visible everywhere within
    one polling tick.

    For each slug, only the most recent build job is returned (newer jobs
    supersede older ones — e.g. a rebuild over a previously-done project).
    """
    out = {}  # slug -> state dict
    if not os.path.isdir(BUILDS_DIR):
        return jsonify({"states": out})
    try:
        for fname in os.listdir(BUILDS_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(BUILDS_DIR, fname)
            try:
                with open(fpath) as f:
                    d = json.load(f)
            except Exception:
                continue
            slug = d.get("project_slug")
            if not slug:
                continue
            updated = d.get("updated_at") or d.get("started_at") or ""
            existing = out.get(slug)
            if existing and (existing.get("updated_at") or "") >= updated:
                continue
            build_id = d.get("build_id")
            zip_exists = bool(build_id) and os.path.isfile(
                os.path.join(BUILDS_DIR, f"{build_id}.zip")
            )
            out[slug] = {
                "build_id":   build_id,
                "slug":       slug,
                "status":     d.get("status", "unknown"),
                "message":    d.get("message", ""),
                "account":    d.get("account"),
                "model":      d.get("model"),
                "started_at": d.get("started_at"),
                "updated_at": updated,
                "zip_exists": zip_exists,
            }
        return jsonify({"states": out})
    except Exception as e:
        return jsonify({"error": str(e), "states": out}), 500

def _ideas_by_slug() -> dict:
    """Map slug → idea record from project-ideas.jsonl, so built projects can
    carry their full description (problem, tech_stack, etc.) into the builds UI."""
    out = {}
    jsonl_path = CLAUDE_IDEAS_FILE.replace(".txt", ".jsonl")
    if not os.path.exists(jsonl_path):
        return out
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                key = _idea_slug(rec.get("name", ""))
                if not key:
                    continue
                # Last write wins (newest entry for a given slug after a rebuild).
                out[key] = rec
    except Exception:
        pass
    return out

@app.get("/api/claude/builds")
def list_builds():
    """List built project directories with metadata + original idea description."""
    try:
        if not os.path.isdir(CLAUDE_BUILDS_DIR):
            return jsonify({"builds": []})
        ideas_map = _ideas_by_slug()
        include_backups = request.args.get("include_backups") in ("1", "true", "yes")
        entries = []
        for name in sorted(os.listdir(CLAUDE_BUILDS_DIR)):
            path = os.path.join(CLAUDE_BUILDS_DIR, name)
            if not os.path.isdir(path):
                continue
            if _is_backup_dir(name) and not include_backups:
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
            # Join with original idea — backups won't have a slug match, that's fine.
            idea = ideas_map.get(name) or {}
            entries.append({
                "slug":         name,
                "size":         size,
                "modified":     int(stat.st_mtime),
                "build_id":     build_id,
                "zip_exists":   zip_exists,
                "is_backup":    _is_backup_dir(name),
                "name":         idea.get("name") or name.replace("-", " ").title(),
                "tagline":      idea.get("tagline", ""),
                "problem":      idea.get("problem", ""),
                "target_users": idea.get("target_users", ""),
                "resume_value": idea.get("resume_value", ""),
                "tech_stack":   idea.get("tech_stack", {}),
                "tags":         idea.get("tags", []),
                "difficulty":   idea.get("difficulty", ""),
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

def _safe_build_slug(raw: str) -> str:
    """Sanitize a slug for use as a dir name under CLAUDE_BUILDS_DIR. Allows
    `_` and `.` so backup dirs (e.g. `<slug>_backup_<epoch>`) can be deleted,
    but blocks anything that could escape the builds dir (path separators,
    leading dots, ..)."""
    safe = "".join(c for c in raw if c.isalnum() or c in "-_.")[:96]
    if not safe or safe.startswith(".") or ".." in safe or "/" in safe:
        return ""
    return safe

@app.delete("/api/claude/builds/<slug>")
def delete_build(slug):
    """Delete a built project directory."""
    safe = _safe_build_slug(slug)
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

# ── Quick-capture Notes / Inbox ────────────────────────────────────────
# Lightweight server-backed scratchpad for ideas, bugs, and TODO-style notes
# that come up away from the keyboard. Stored as JSONL at a known path so
# Claude can be pointed at it later and act on the entries.
#
#   File:  /opt/claude-ideas/notes.jsonl
#   Shape: {"id","created_at","updated_at","type","text","status"}
#     type:   "idea" | "bug" | "note"
#     status: "open" | "done"

NOTES_FILE = os.environ.get("NOTES_FILE", "/opt/claude-ideas/notes.jsonl")
VALID_NOTE_TYPES   = {"idea", "bug", "note"}
VALID_NOTE_STATUS  = {"open", "done"}

# ── Claude Chat constants ──────────────────────────────────────────────
# Defined here (above settings) because SETTINGS_DEFAULTS uses them as the
# initial values for the chat section. The chat *endpoints* live further down
# next to the rest of the chat plumbing — only the constants moved up.
#
# Hard safety boundaries — TWO layers because a single layer is a single bug:
#   (1) CLI layer: --allowedTools restricted at invocation time. The model
#       literally cannot invoke a tool not in the allow list.
#   (2) Prompt layer: a system prompt that explicitly refuses modifications,
#       network calls, credential reads, and infra changes. If the CLI flag
#       ever drifts, the model still refuses.
# Both are user-tunable via /api/settings so the prompt and tool list can be
# edited without a rebuild.

CHAT_LOG_FILE        = os.environ.get("CHAT_LOG_FILE",        "/opt/claude-ideas/chat.jsonl")
CHAT_SESSIONS_DIR    = os.environ.get("CHAT_SESSIONS_DIR",    "/opt/claude-ideas/chat-sessions")

# Where the chatbot is allowed to look. Claude Code sandboxes its file tools
# (Read/Glob/Grep/Edit) to the working directory and whatever is passed via
# --add-dir. Without this the bot runs in /app (WORKDIR) — which only holds
# app.py + dashboard.html — so every grep/read of the data dirs came back
# empty. CHAT_CWD is the primary root (the dashboard source); CHAT_ADD_DIRS
# are the other mounted trees the bot reasons about. Only list paths that are
# actually mounted into the container (see docker-compose volumes).
CHAT_CWD      = "/app"
CHAT_ADD_DIRS = [
    "/opt/claude-ideas",        # ideas, notes, builds queue, generator logs, settings
    "/home/luis/claude-builds", # finished build outputs
]
CHAT_MAX_HISTORY     = 12      # turns of context sent back to claude (6 user + 6 assistant)
CHAT_TIMEOUT_SEC     = 90      # per-message wall clock
CHAT_SESSION_TTL     = 7 * 86400  # auto-expire dormant sessions after a week

# Default homelab-specific context. This is the *what your tools can see* part
# of the system prompt — informational, not a rule. Editable as a textarea in
# the settings page.
CHAT_DEFAULT_CONTEXT = """- Homelab runs Docker services: dashboard-api (Flask, this app), homepage, glances, Nextcloud backup target, Home Assistant twin, Caddy reverse proxy.
- Idea generator scripts: `/home/luis/scripts/claude-ideas/claude-idea-generator.sh`, build runner, watcher.
- Data files: `/opt/claude-ideas/{project-ideas.jsonl, graveyard.jsonl, notes.jsonl, generator.log, limits.json}`. Built projects live at `/home/luis/claude-builds/<slug>/`.
- The dashboard source (your own code) is your working directory: `/app/{app.py, dashboard.html}`. The data dirs `/opt/claude-ideas` and `/home/luis/claude-builds` are also readable."""

# Safety + style rules. Each one becomes a checkbox on the settings page; the
# composed system prompt only includes the lines whose rule is enabled.
# Capability is driven by `allowed_tools`: adding Edit/Write/Bash to that list
# auto-drops the contradicting refusal in _compose_chat_prompt, so you flip one
# switch (the tool list), not two. Leaving a tool out keeps both layers locked.
#
# Format: rule key → (prompt_section, prompt_line). prompt_section is one of
# "hard" (refusals) or "style" (response shape).
CHAT_RULES_SPEC = {
    "no_file_writes":      ("hard",  "- Do not modify files. No edits, writes, deletes, moves, mkdir, chmod, chown."),
    "no_shell_commands":   ("hard",  "- Do not run shell commands or invoke Bash in any form, even via Read of a script."),
    "no_network_calls":    ("hard",  "- Do not make network requests (no curl, no fetch, no API calls beyond what you already have)."),
    "no_credential_reads": ("hard",  "- Do not read credential files: `.credentials.json`, any `*.env` file, `oauth-tokens.env`, `.secrets`, anything under `/etc/ssl`, `/root`, or named `*token*` / `*secret*`. If asked, refuse and say which file you would have refused."),
    "no_service_control":  ("hard",  "- Do not restart services, touch systemd, docker, or git."),
    "flag_destructive":    ("hard",  "- Do not propose destructive actions for the user to run without explicitly flagging the blast radius (e.g. `rm -rf`, `git reset --hard`, `docker compose down -v`)."),
    "terse_style":         ("style", "- Terse. Direct. No filler."),
    "cite_file_lines":     ("style", "- Use file:line references when pointing at code. Use backticks for paths, commands, identifiers."),
    "admit_unknowns":      ("style", "- If you don't know, say so. Don't guess at file contents — Read them."),
}

# Defaults match the previous hardcoded prompt (everything ON) so the
# behavior change is opt-in via the settings UI.
CHAT_RULES_DEFAULTS = {k: True for k in CHAT_RULES_SPEC}


def _compose_chat_prompt(cfg: dict) -> str:
    """Build the system prompt from the structured rules + context. Lets the
    user untoggle e.g. no_shell_commands to actually unlock Bash, instead of
    fighting a frozen monolithic prompt."""
    rules = dict(cfg.get("rules") or {})
    context = (cfg.get("context") or "").strip()
    allowed = cfg.get("allowed_tools") or "Read,Glob,Grep"
    allowed_set = {t.strip() for t in allowed.split(",") if t.strip()}

    # Reconcile the refusal rules with the actual tool list so a tool can never
    # be "allowed but silently refused". If the user adds a capability to
    # allowed_tools, the contradicting hard rule is dropped automatically — one
    # switch, not two. The read-only default keeps every write tool OUT of
    # allowed_tools, so these refusals still fire (defense in depth holds).
    if allowed_set & {"Edit", "Write"}:
        rules["no_file_writes"] = False
    if "Bash" in allowed_set:
        rules["no_shell_commands"] = False
    if allowed_set & {"WebFetch", "WebSearch"}:
        rules["no_network_calls"] = False

    parts = [
        f"You are the chatbot embedded in Luis's homelab dashboard. You run inside the dashboard's Flask API on the homelab server and are invoked via `claude -p` with tools restricted to: {allowed}."
    ]

    hard  = [line for k, (sect, line) in CHAT_RULES_SPEC.items() if sect == "hard"  and rules.get(k, CHAT_RULES_DEFAULTS[k])]
    style = [line for k, (sect, line) in CHAT_RULES_SPEC.items() if sect == "style" and rules.get(k, CHAT_RULES_DEFAULTS[k])]

    if hard:
        parts.append("\nHARD RULES (refuse, do not attempt):")
        parts.extend(hard)
        parts.append("\nIf a request would require any of the above, say so plainly in one sentence and suggest a safer alternative.")
    if context:
        parts.append("\nCONTEXT you can rely on:")
        parts.append(context)
    if style:
        parts.append("\nSTYLE:")
        parts.extend(style)
    return "\n".join(parts)

# ── Runtime settings ───────────────────────────────────────────────────
# Single source of truth for tunables that need to change without a rebuild
# (chatbot prompt, allowed tools, timeouts, model defaults, etc.). Lives at
# /opt/claude-ideas/settings.json — same writable mount the rest of the
# claude-ideas state uses. Shell scripts (generator, build runner) read this
# file directly via a python one-liner so behavior stays consistent.
#
# Layering: SETTINGS_DEFAULTS is the floor; the file on disk only stores
# overrides, so deleting it (or POSTing /api/settings/reset) restores the
# defaults atomically.

SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "/opt/claude-ideas/settings.json")

SETTINGS_DEFAULTS = {
    "chat": {
        # Safety/style toggles. Untick to actually unlock the corresponding
        # tool — e.g. uncheck `no_shell_commands` and add Bash to allowed_tools
        # for a bot that can run commands.
        "rules":         dict(CHAT_RULES_DEFAULTS),
        # Informational context appended to the prompt — describes what's
        # where on the server. Edit freely; not a guardrail.
        "context":       CHAT_DEFAULT_CONTEXT,
        "allowed_tools": "Read,Glob,Grep",
        "timeout_sec":   CHAT_TIMEOUT_SEC,
        "max_history":   CHAT_MAX_HISTORY,
        "default_model": "sonnet",
        # When an account's 5h utilization is at or above this percent it's
        # treated as throttled and skipped during account rotation.
        "throttle_threshold_pct": 95,
        # Max characters the user can send in a single message. Anything
        # longer is rejected before we spend a token.
        "message_max_chars": 8000,
        # Idle sessions get pruned after this many days. Keeps chat-sessions/
        # from growing without bound.
        "session_ttl_days": 7,
    },
    "generator": {
        "github_user":         "lmbraca",
        "github_cache_hours":  24,
        # Idea *quality* lives or dies on this model. haiku produced weak,
        # generic ideas; sonnet is the floor for usable ideation. Bump to
        # opus in settings if you want the best ideas and can spend the limit.
        "model":               "sonnet",
        # Wall clock for the GitHub portfolio fetch. Failure is non-fatal —
        # the generator falls back to the stale cache.
        "github_fetch_timeout_sec": 10,
        # build-watcher.sh sleep between job dir scans. Lower = builds start
        # faster; higher = less CPU when idle.
        "watcher_poll_sec": 5,
        # alert-claude-limits.sh thresholds: consecutive failed checks before
        # paging, and the max age of .last_refresh before staleness alerts.
        "alert_failure_threshold": 2,
        "alert_stale_hours":      36,
    },
    "builds": {
        # Per-build wall clock for `claude -p` inside run-build.sh. Anything
        # longer is considered hung and the build is killed.
        "timeout_minutes": 10,
    },
    "dashboard": {
        # Max hours a generator account can be silent before /api/claude/log-stats
        # marks it stalled. Accounts have a 6h overnight gap, so anything <8 is
        # too noisy.
        "stall_hours": 8,
        # Theme on first load: auto follows sunrise/sunset, dark/light pin.
        "default_theme": "auto",
        # Used for the auto-theme sunrise/sunset calculation. Default = bracas
        # server location (Mexicali). Change if the dashboard moves.
        "location_lat": 32.6245,
        "location_lon": -115.4683,
        # Widget poll intervals (seconds). Apply on page load — change requires
        # a refresh to take effect.
        "poll_servers_sec":       10,
        "poll_storage_sec":       60,
        "poll_backup_sec":         4,
        "poll_twin_sec":           8,
        "poll_tailscale_sec":     30,
        "poll_notes_sec":         30,
        "poll_ideas_sec":         60,
        "poll_builds_sec":        30,
        "poll_build_states_sec":  10,
        "poll_claude_usage_sec": 300,
        "poll_chat_status_sec":   60,
        "poll_build_log_sec":      8,
    },
    "health": {
        # System-check thresholds. Bash script (`system-check.sh`) reads these
        # from settings.json on each run. Tune if your hardware skews the
        # default "alert at 90%" line (e.g. low-RAM box should warn earlier).
        "cpu_overload_ratio":         1.0,  # loadavg / cores; >1 = fail
        "memory_critical_pct":         90,
        "memory_warning_pct":          75,
        "disk_critical_pct":           90,
        "disk_warning_pct":            75,
        "swap_warning_pct":            50,
        "updates_warn_count":          20,
        "docker_restart_warn_count":    5,
    },
}

# Whitelist of (section, key) → validator. Anything not in here is rejected on
# PATCH so a typo or a malicious client can't dump arbitrary keys into the file.
def _validate_str(v, max_len=8000):
    if not isinstance(v, str): return None
    s = v.strip()
    return s[:max_len] if s else None

def _validate_int(lo, hi):
    def _v(x):
        try:
            n = int(x)
        except Exception:
            return None
        if n < lo or n > hi:
            return None
        return n
    return _v

def _validate_choice(choices):
    def _v(x):
        return x if x in choices else None
    return _v

def _validate_tools(v):
    if not isinstance(v, str):
        return None
    allowed = {"Read", "Glob", "Grep", "Bash", "Edit", "Write",
               "WebFetch", "WebSearch", "Task", "TodoWrite"}
    parts = [p.strip() for p in v.split(",") if p.strip()]
    cleaned = [p for p in parts if p in allowed]
    return ",".join(dict.fromkeys(cleaned))  # de-dup, preserve order

def _validate_float(lo, hi):
    def _v(x):
        try:
            n = float(x)
        except Exception:
            return None
        if n < lo or n > hi:
            return None
        return n
    return _v

def _validate_chat_rules(v):
    if not isinstance(v, dict):
        return None
    cleaned = {}
    for k, val in v.items():
        if k in CHAT_RULES_SPEC and isinstance(val, bool):
            cleaned[k] = val
    return cleaned if cleaned else None

SETTINGS_VALIDATORS = {
    ("chat", "rules"):                  _validate_chat_rules,
    # context may be intentionally cleared, so an empty string is valid.
    ("chat", "context"):                lambda v: (v[:16000] if isinstance(v, str) else None),
    ("chat", "allowed_tools"):          _validate_tools,
    ("chat", "timeout_sec"):            _validate_int(10, 600),
    ("chat", "max_history"):            _validate_int(0, 60),
    ("chat", "default_model"):          _validate_choice({"haiku", "sonnet", "opus"}),
    ("chat", "throttle_threshold_pct"): _validate_int(0, 100),
    ("chat", "message_max_chars"):      _validate_int(100, 32000),
    ("chat", "session_ttl_days"):       _validate_int(1, 365),
    ("generator", "github_user"):              lambda v: _validate_str(v, 64),
    ("generator", "github_cache_hours"):       _validate_int(1, 168),
    ("generator", "model"):                    _validate_choice({"haiku", "sonnet", "opus"}),
    ("generator", "github_fetch_timeout_sec"): _validate_int(2, 60),
    ("generator", "watcher_poll_sec"):         _validate_int(1, 60),
    ("generator", "alert_failure_threshold"):  _validate_int(1, 20),
    ("generator", "alert_stale_hours"):        _validate_int(1, 720),
    ("builds",    "timeout_minutes"):    _validate_int(1, 120),
    ("dashboard", "stall_hours"):             _validate_int(1, 168),
    ("dashboard", "default_theme"):           _validate_choice({"auto", "dark", "light"}),
    ("dashboard", "location_lat"):            _validate_float(-90, 90),
    ("dashboard", "location_lon"):            _validate_float(-180, 180),
    ("dashboard", "poll_servers_sec"):        _validate_int(2, 3600),
    ("dashboard", "poll_storage_sec"):        _validate_int(5, 3600),
    ("dashboard", "poll_backup_sec"):         _validate_int(1, 3600),
    ("dashboard", "poll_twin_sec"):           _validate_int(2, 3600),
    ("dashboard", "poll_tailscale_sec"):      _validate_int(5, 3600),
    ("dashboard", "poll_notes_sec"):          _validate_int(5, 3600),
    ("dashboard", "poll_ideas_sec"):          _validate_int(5, 3600),
    ("dashboard", "poll_builds_sec"):         _validate_int(5, 3600),
    ("dashboard", "poll_build_states_sec"):   _validate_int(2, 3600),
    ("dashboard", "poll_claude_usage_sec"):   _validate_int(10, 3600),
    ("dashboard", "poll_chat_status_sec"):    _validate_int(5, 3600),
    ("dashboard", "poll_build_log_sec"):      _validate_int(2, 3600),
    ("health", "cpu_overload_ratio"):        _validate_float(0.1, 10),
    ("health", "memory_critical_pct"):       _validate_int(50, 100),
    ("health", "memory_warning_pct"):        _validate_int(0, 100),
    ("health", "disk_critical_pct"):         _validate_int(50, 100),
    ("health", "disk_warning_pct"):          _validate_int(0, 100),
    ("health", "swap_warning_pct"):          _validate_int(0, 100),
    ("health", "updates_warn_count"):        _validate_int(1, 1000),
    ("health", "docker_restart_warn_count"): _validate_int(1, 100),
}

def _load_settings_overrides() -> dict:
    if not os.path.isfile(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _effective_settings() -> dict:
    """Return defaults deep-merged with on-disk overrides."""
    import copy
    out = copy.deepcopy(SETTINGS_DEFAULTS)
    overrides = _load_settings_overrides()
    for section, values in overrides.items():
        if not isinstance(values, dict) or section not in out:
            continue
        for key, val in values.items():
            if key in out[section]:
                out[section][key] = val
    return out

def _setting(section: str, key: str):
    """Helper for code paths that just need one value."""
    return _effective_settings().get(section, {}).get(key, SETTINGS_DEFAULTS[section][key])

def _write_settings_overrides(overrides: dict):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(overrides, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)
    try: os.chmod(SETTINGS_FILE, 0o666)
    except Exception: pass

@app.get("/api/settings")
def get_settings():
    """Current settings (defaults overlaid with on-disk overrides) plus the
    raw defaults so the UI can render a 'reset this field' affordance."""
    return jsonify({
        "settings": _effective_settings(),
        "defaults": SETTINGS_DEFAULTS,
        "overrides": _load_settings_overrides(),
    })

@app.patch("/api/settings")
def patch_settings():
    """Merge a subset of settings into the override file. Unknown keys are
    silently dropped; invalid values are rejected with 400."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "body must be an object"}), 400
    current = _load_settings_overrides()
    rejected = []
    applied = {}
    for section, values in body.items():
        if not isinstance(values, dict):
            continue
        for key, raw_val in values.items():
            validator = SETTINGS_VALIDATORS.get((section, key))
            if validator is None:
                rejected.append(f"{section}.{key}: unknown key")
                continue
            cleaned = validator(raw_val)
            if cleaned is None:
                rejected.append(f"{section}.{key}: invalid value")
                continue
            current.setdefault(section, {})[key] = cleaned
            applied.setdefault(section, {})[key] = cleaned
    if rejected and not applied:
        return jsonify({"error": "no valid updates", "rejected": rejected}), 400
    _write_settings_overrides(current)
    return jsonify({"ok": True, "applied": applied, "rejected": rejected,
                    "settings": _effective_settings()})

@app.post("/api/settings/reset")
def reset_settings():
    """Drop all overrides — settings revert to defaults. Body: {section?: str}
    restricts the reset to one section."""
    body = request.get_json(silent=True) or {}
    section = (body.get("section") or "").strip() if isinstance(body, dict) else ""
    current = _load_settings_overrides()
    if section:
        if section not in SETTINGS_DEFAULTS:
            return jsonify({"error": "unknown section"}), 400
        current.pop(section, None)
        _write_settings_overrides(current)
    else:
        try:
            if os.path.isfile(SETTINGS_FILE):
                os.remove(SETTINGS_FILE)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "settings": _effective_settings()})



def _load_notes():
    if not os.path.exists(NOTES_FILE):
        return []
    out = []
    with open(NOTES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

def _write_notes(notes):
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    tmp = NOTES_FILE + ".tmp"
    with open(tmp, "w") as f:
        for n in notes:
            f.write(json.dumps(n) + "\n")
    os.replace(tmp, NOTES_FILE)
    try: os.chmod(NOTES_FILE, 0o666)
    except Exception: pass

@app.get("/api/notes")
def list_notes():
    try:
        notes = _load_notes()
        notes.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        return jsonify({"notes": notes[:200], "total": len(notes)})
    except Exception as e:
        return jsonify({"error": str(e), "notes": []}), 500

@app.post("/api/notes")
def create_note():
    try:
        body  = request.get_json() or {}
        text  = (body.get("text") or "").strip()
        ntype = (body.get("type") or "note").strip().lower()
        if not text:
            return jsonify({"error": "text is required"}), 400
        if ntype not in VALID_NOTE_TYPES:
            ntype = "note"
        now = datetime.now(timezone.utc).isoformat()
        note = {
            "id":         uuid.uuid4().hex[:10],
            "created_at": now,
            "updated_at": now,
            "type":       ntype,
            "text":       text[:4000],
            "status":     "open",
        }
        # Append-only fast path; full rewrite only happens on edit/delete.
        os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
        with open(NOTES_FILE, "a") as f:
            f.write(json.dumps(note) + "\n")
        try: os.chmod(NOTES_FILE, 0o666)
        except Exception: pass
        return jsonify({"ok": True, "note": note})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.patch("/api/notes/<note_id>")
def update_note(note_id):
    safe = "".join(c for c in note_id if c.isalnum())[:32]
    if not safe:
        return jsonify({"error": "invalid id"}), 400
    body = request.get_json() or {}
    notes = _load_notes()
    for n in notes:
        if n.get("id") == safe:
            if "status" in body and body["status"] in VALID_NOTE_STATUS:
                n["status"] = body["status"]
            if "type" in body and body["type"] in VALID_NOTE_TYPES:
                n["type"] = body["type"]
            if "text" in body and isinstance(body["text"], str):
                t = body["text"].strip()
                if t:
                    n["text"] = t[:4000]
            n["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_notes(notes)
            return jsonify({"ok": True, "note": n})
    return jsonify({"error": "not found"}), 404

@app.delete("/api/notes/<note_id>")
def delete_note(note_id):
    safe = "".join(c for c in note_id if c.isalnum())[:32]
    if not safe:
        return jsonify({"error": "invalid id"}), 400
    notes = _load_notes()
    new = [n for n in notes if n.get("id") != safe]
    if len(new) == len(notes):
        return jsonify({"error": "not found"}), 404
    _write_notes(new)
    return jsonify({"ok": True, "remaining": len(new)})

# ── Claude Chat (dashboard chatbot) ────────────────────────────────────
# Read-only Claude embedded in the dashboard. Rotates across the same three
# accounts the idea generator uses, falls back through 2→3 as each hits its
# 5h ceiling, and surfaces a reset ETA when all three are spent. Every turn
# is logged to chat.jsonl so a misbehaving response leaves a trail. Constants
# (system prompt, allowed tools, timeouts) live above next to SETTINGS_DEFAULTS
# since they're also user-tunable via /api/settings.

def _safe_session_id(raw: str) -> str:
    """Allow hex/uuid-ish ids only; block path tricks."""
    s = "".join(c for c in (raw or "") if c.isalnum() or c in "-_")[:64]
    if not s or s.startswith(".") or ".." in s:
        return ""
    return s


def _pick_chat_account() -> tuple:
    """Pick the first account whose 5h session has headroom. Returns
    (account_int, None) on success, or (None, reset_eta_human_str) if all
    accounts are throttled. Uses the same limits.json the dashboard already
    reads — no extra fetch."""
    soonest_reset = None
    soonest_iso = None
    if not os.path.isfile(CLAUDE_LIMITS_FILE):
        # No data — assume account 1 is fine (rate limits will surface as 429s
        # from claude -p itself and we'll fall through on retry).
        return 1, None
    try:
        with open(CLAUDE_LIMITS_FILE) as f:
            raw = json.load(f)
    except Exception:
        return 1, None
    threshold = _setting("chat", "throttle_threshold_pct")
    for acct in CLAUDE_ACCOUNTS:
        entry = raw.get(str(acct)) or {}
        data  = entry.get("data") or {}
        five  = data.get("five_hour") or {}
        util  = float(five.get("utilization") or 0)
        resets_at = five.get("resets_at") or ""
        if util < threshold:
            return acct, None
        if resets_at and (soonest_iso is None or resets_at < soonest_iso):
            soonest_iso = resets_at
            soonest_reset = fmt_resets(resets_at)
    return None, (soonest_reset or "soon")


def _chat_session_path(sid: str) -> str:
    return os.path.join(CHAT_SESSIONS_DIR, f"{sid}.jsonl")


def _load_chat_history(sid: str) -> list:
    path = _chat_session_path(sid)
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _append_chat_turn(sid: str, turn: dict):
    os.makedirs(CHAT_SESSIONS_DIR, exist_ok=True)
    path = _chat_session_path(sid)
    with open(path, "a") as f:
        f.write(json.dumps(turn) + "\n")
    try: os.chmod(path, 0o666)
    except Exception: pass


def _append_chat_log(rec: dict):
    """Audit log — every turn across every session lands here so a regression
    or a misbehaving response can always be reconstructed."""
    try:
        os.makedirs(os.path.dirname(CHAT_LOG_FILE), exist_ok=True)
        with open(CHAT_LOG_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
        try: os.chmod(CHAT_LOG_FILE, 0o666)
        except Exception: pass
    except Exception:
        pass


def _format_history_for_prompt(history: list, max_turns: int) -> str:
    """Render the last N turns as a transcript block for the prompt."""
    if not history:
        return ""
    tail = history[-max_turns:]
    lines = []
    for t in tail:
        role = t.get("role", "user")
        msg  = (t.get("content") or "").strip()
        if not msg:
            continue
        lines.append(f"{role}: {msg}")
    if not lines:
        return ""
    return "\n\nCONVERSATION HISTORY (most recent last):\n" + "\n".join(lines)


@app.post("/api/claude/chat")
def chat_send():
    """Send a message to the dashboard chatbot. Picks the first non-throttled
    account, runs `claude -p` with read-only tools, returns the response.

    Body: {message: str, conversation_id?: str, model?: str}
    Returns: {ok, conversation_id, account, model, reply, duration_ms}
             or {ok: false, throttled: true, reset_eta: str} (503) if all
             accounts are spent.
    """
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    # Pull every tunable from settings once so a runtime change takes effect
    # on the very next message without a rebuild. The system prompt is
    # *composed* on each request from the rule toggles + context — that's how
    # unchecking e.g. "refuse shell commands" actually unlocks Bash.
    chat_cfg      = _effective_settings()["chat"]
    system_prompt = _compose_chat_prompt(chat_cfg)
    allowed_tools = chat_cfg["allowed_tools"]
    timeout_sec   = chat_cfg["timeout_sec"]
    max_history   = chat_cfg["max_history"]
    default_model = chat_cfg["default_model"]
    max_chars     = chat_cfg["message_max_chars"]
    if len(message) > max_chars:
        return jsonify({"error": f"message too long ({max_chars} char max)"}), 400

    sid = _safe_session_id(body.get("conversation_id") or "") or uuid.uuid4().hex[:16]
    requested_model = (body.get("model") or default_model).strip()
    model_map = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}
    model = model_map.get(requested_model, requested_model)
    if model not in VALID_MODELS:
        return jsonify({"error": f"invalid model: {requested_model}"}), 400

    acct, reset_eta = _pick_chat_account()
    if acct is None:
        return jsonify({
            "ok": False,
            "throttled": True,
            "reset_eta": reset_eta,
            "message": f"All three accounts are at their 5h limit. Soonest reset: {reset_eta}.",
        }), 503

    history = _load_chat_history(sid)
    history_block = _format_history_for_prompt(history, max_history)
    full_prompt = (
        system_prompt
        + history_block
        + f"\n\nCURRENT MESSAGE:\nuser: {message}\n\nRespond as the assistant."
    )

    config_dir = CLAUDE_CONFIG_DIRS[acct]
    creds_path = os.path.join(config_dir, ".credentials.json")
    if not os.path.isfile(creds_path):
        return jsonify({"error": f"account {acct} not logged in"}), 500

    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": config_dir,
        "HOME": "/home/luis",
    }
    # Same scrub as the generator — never let API/Bedrock/Vertex env vars
    # bypass the subscription credentials we want to bill against.
    for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        env.pop(k, None)

    started = time.monotonic()
    started_iso = datetime.now(timezone.utc).isoformat()
    error = None
    reply = ""
    try:
        # --allowedTools restricts the model to whatever the settings page
        # has whitelisted. Layer 1 of the safety boundary; the system prompt
        # (also editable in settings) is layer 2.
        # cwd + --add-dir grant the file tools access to the mounted data
        # trees; without them Read/Glob/Grep are sandboxed to /app and see
        # only the source. Access != mutation — writes still require Edit/Write
        # in allowed_tools (read-only by default).
        cmd = [
            "claude", "-p", full_prompt,
            "--model", model,
            "--no-session-persistence",
            "--allowedTools", allowed_tools,
        ]
        for d in CHAT_ADD_DIRS:
            if os.path.isdir(d):
                cmd += ["--add-dir", d]
        result = subprocess.run(
            cmd,
            cwd=CHAT_CWD if os.path.isdir(CHAT_CWD) else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        if result.returncode != 0:
            error = (result.stderr or "claude exited non-zero").strip()[:500]
        else:
            reply = (result.stdout or "").strip()
    except subprocess.TimeoutExpired:
        error = f"timeout after {timeout_sec}s"
    except Exception as e:
        error = str(e)[:500]

    duration_ms = int((time.monotonic() - started) * 1000)
    finished_iso = datetime.now(timezone.utc).isoformat()

    log_rec = {
        "ts":           started_iso,
        "finished_at":  finished_iso,
        "conversation_id": sid,
        "account":      acct,
        "model":        model,
        "user_msg":     message,
        "assistant_msg": reply,
        "duration_ms":  duration_ms,
        "error":        error,
    }
    _append_chat_log(log_rec)

    if error:
        return jsonify({
            "ok": False,
            "conversation_id": sid,
            "account": acct,
            "model": model,
            "error": error,
            "duration_ms": duration_ms,
        }), 502

    # Persist both turns so the next message has context.
    _append_chat_turn(sid, {"role": "user", "content": message,
                             "ts": started_iso, "account": acct, "model": model})
    _append_chat_turn(sid, {"role": "assistant", "content": reply,
                             "ts": finished_iso, "account": acct, "model": model,
                             "duration_ms": duration_ms})

    return jsonify({
        "ok": True,
        "conversation_id": sid,
        "account": acct,
        "model": model,
        "reply": reply,
        "duration_ms": duration_ms,
    })


@app.get("/api/claude/chat/<conversation_id>")
def chat_history(conversation_id):
    sid = _safe_session_id(conversation_id)
    if not sid:
        return jsonify({"error": "invalid id"}), 400
    return jsonify({"conversation_id": sid, "turns": _load_chat_history(sid)})


@app.delete("/api/claude/chat/<conversation_id>")
def chat_clear(conversation_id):
    sid = _safe_session_id(conversation_id)
    if not sid:
        return jsonify({"error": "invalid id"}), 400
    path = _chat_session_path(sid)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "conversation_id": sid})


@app.get("/api/claude/chat-status")
def chat_status():
    """Pre-flight: which account would answer right now, or is everything throttled?
    Lets the UI render the limits-reached state without sending a wasted message."""
    acct, reset_eta = _pick_chat_account()
    default_model = _setting("chat", "default_model")
    if acct is None:
        return jsonify({"throttled": True, "reset_eta": reset_eta, "default_model": default_model})
    return jsonify({"throttled": False, "account": acct, "default_model": default_model})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787)
