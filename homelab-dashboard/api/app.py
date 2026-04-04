import json
import os
import subprocess
from datetime import datetime, timezone
import urllib.request
from flask import Flask, jsonify, request, send_from_directory
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787)
