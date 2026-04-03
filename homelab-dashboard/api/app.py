import json
import os
import subprocess
from datetime import datetime, timezone
import urllib.request
from flask import Flask, jsonify

app = Flask(__name__)

def run(cmd):
    return subprocess.check_output(cmd, text=True)

def iso_to_age_label(iso_str):
    try:
        t = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - t
        sec = int(delta.total_seconds())
        if sec < 60:
            return f"{sec}s ago"
        if sec < 3600:
            return f"{sec//60}m ago"
        if sec < 86400:
            return f"{sec//3600}h ago"
        return f"{sec//86400}d ago"
    except Exception:
        return iso_str

def find_nextcloud_data_dir():
    env = os.environ.get("NEXTCLOUD_DATA_DIR")
    if env and os.path.isdir(env):
        return env

    candidates = [
        "/var/www/nextcloud/data",
        "/srv/nextcloud/data",
        "/mnt/nextcloud/data",
        "/var/snap/nextcloud/common/nextcloud/data",
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return None

def human(n: float) -> str:
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}EB"

@app.get("/api/tailscale")
def tailscale():
    raw = run(["tailscale", "status", "--json"])
    data = json.loads(raw)

    peers = data.get("Peer", {}) or {}
    items = []

    for _k, p in peers.items():
        name = p.get("HostName") or p.get("DNSName") or p.get("Name") or "unknown"
        ip = (p.get("TailscaleIPs") or [""])[0]
        online = bool(p.get("Online", False))
        last_seen = p.get("LastSeen")
        last_label = iso_to_age_label(last_seen) if last_seen else "n/a"
        status = "online" if online else f"offline ({last_label})"
        items.append({"name": name, "label": f"{ip} • {status}"})

    items.sort(key=lambda x: (0 if "online" in x["label"] else 1, x["name"].lower()))
    return jsonify({"results": {"devices": items}})

@app.get("/api/tailscale-text")
def tailscale_text():
    items = []
    try:
        raw = run(["tailscale", "status", "--json"])
        data = json.loads(raw)
        peers = data.get("Peer", {}) or {}

        for _k, p in peers.items():
            name = p.get("HostName") or p.get("DNSName") or p.get("Name") or "unknown"
            ip = (p.get("TailscaleIPs") or [""])[0]
            online = bool(p.get("Online", False))
            last_seen = p.get("LastSeen")
            last_label = iso_to_age_label(last_seen) if last_seen else "n/a"
            status = "ONLINE" if online else f"OFFLINE ({last_label})"
            items.append((0 if online else 1, name.lower(), name, ip, status))

        items.sort()
        lines = [f"- {name} — {ip} — {status}" for _, __, name, ip, status in items]
        return jsonify({"text": "\n".join(lines)})
    except Exception as e:
        return jsonify({"text": f"- tailscale error: {type(e).__name__}"})

@app.get("/api/nextcloud-disk-text")
def nextcloud_disk_text():
    p = find_nextcloud_data_dir()
    if not p:
        return jsonify({"text": "Path: (not found)<br>Total: n/a<br>Used: n/a<br>Free: n/a"})

    st = os.statvfs(p)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    pct = (used / total * 100) if total else 0

    return jsonify({
        "text": (
            f"Path: {p}\n"
            f"Total: {human(total)}\n"
            f"Used: {human(used)} ({pct:.1f}%)\n"
            f"Free: {human(free)}"
        )
    })

@app.get("/api/nextcloud-disk-fields")
def nextcloud_disk_fields():
    p = find_nextcloud_data_dir()
    if not p:
        return jsonify({"path":"(not found)","total":"n/a","used":"n/a","free":"n/a","pct":"n/a"})
    st = os.statvfs(p)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    pct = (used / total * 100) if total else 0
    return jsonify({
        "path": p,
        "total": human(total),
        "used": human(used),
        "free": human(free),
        "pct": f"{pct:.1f}%"
    })
@app.get("/api/backup-disk-fields")
def backup_disk_fields():
    # Backup server Glances URL (tailscale IP)
    url = "http://100.90.102.52:61208/api/4/fs"

    try:

        raw = urllib.request.urlopen(url, timeout=4).read().decode("utf-8")
        data = json.loads(raw)

        if not isinstance(data, list) or not data:
            return jsonify({
                "path": "(no data)",
                "total": "n/a",
                "used": "n/a",
                "free": "n/a",
                "pct": "n/a",
            })

        # Normalize mountpoint key across possible Glances versions
        def mountpoint(it):
            return it.get("mnt_point") or it.get("mountpoint") or it.get("path")

        # Normalize numeric fields across possible Glances versions
        def get_total(it):
            return it.get("size") or it.get("total") or 0

        def get_used(it):
            return it.get("used") or 0

        def get_free(it):
            # Sometimes provided directly; otherwise compute
            f = it.get("free")
            if f is None:
                f = get_total(it) - get_used(it)
            return f

        def get_pct(it):
            p = it.get("percent")
            if p is None:
                tot = get_total(it)
                p = (get_used(it) / tot * 100) if tot else 0
            return p

        # 1) Prefer the root mount "/"
        root = None
        for it in data:
            if mountpoint(it) == "/":
                root = it
                break

        # 2) Fallback: pick the largest filesystem (usually the main disk)
        if root is None:
            root = max(data, key=lambda it: float(get_total(it) or 0))

        mp = mountpoint(root) or "/"
        total = float(get_total(root) or 0)
        used = float(get_used(root) or 0)
        free = float(get_free(root) or 0)
        pct = float(get_pct(root) or 0)

        return jsonify({
            "path": mp,
            "total": human(total),
            "used": human(used),
            "free": human(free),
            "pct": f"{pct:.1f}%",
        })

    except Exception as e:
        return jsonify({
            "path": "(error)",
            "total": "n/a",
            "used": "n/a",
            "free": "n/a",
            "pct": type(e).__name__,
        })

@app.get("/api/nextcloud-disk")
def nextcloud_disk():
    p = find_nextcloud_data_dir()
    if not p:
    	return jsonify({
        	"results": {
            		"items": [{"name": "Nextcloud", "label": "data dir not found"}]
        	}
    	})

    st = os.statvfs(p)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail

    return jsonify({
        "results": {
            "items": [
                {"name": p, "label": f"free {human(free)} / total {human(total)}"}
            ]
        }
    })

HA_URL = os.environ.get("HA_URL", "http://localhost:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

def ha_get(path):
    req = urllib.request.Request(
        f"{HA_URL}/api/{path}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=4).read())

@app.get("/api/ha/lights")
def ha_lights():
    try:
        states = ha_get("states")
        lights = [s for s in states if s["entity_id"].startswith("light.")]
        items = []
        for l in lights:
            attrs = l.get("attributes", {})
            items.append({
                "name": attrs.get("friendly_name", l["entity_id"]),
                "state": l["state"],
                "brightness_pct": round(attrs["brightness"] / 255 * 100) if attrs.get("brightness") else None
            })
        return jsonify({"lights": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/ha/summary")
def ha_summary():
    try:
        states = ha_get("states")
        lights_on = sum(1 for s in states if s["entity_id"].startswith("light.") and s["state"] == "on")
        lights_total = sum(1 for s in states if s["entity_id"].startswith("light."))
        return jsonify({
            "lights": f"{lights_on}/{lights_total} on",
            "total_entities": len(states)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787)
