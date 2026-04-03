"""
Digital Twin REST API
Exposes HA devices with twin metadata (rooms, 3D positions).
Zigbee devices appear automatically once paired via Z2M → HA.
"""
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from ha_client import HomeAssistantClient, HAError
import db

app = Flask(__name__)
CORS(app)

# ── Helpers ────────────────────────────────────────────────────────────

def ha():
    return HomeAssistantClient()

def err(msg, code=400):
    return jsonify({"error": msg}), code

def ok(data=None, **kw):
    body = {"ok": True, **kw}
    if data is not None:
        body["data"] = data
    return jsonify(body)

def slugify(name):
    return name.lower().strip().replace(" ", "_").replace("-", "_")

# ── Health ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        client = ha()
        alive  = client.ping()
    except HAError as e:
        return jsonify({"status": "degraded", "error": str(e)}), 503

    registered = len(db.get_all_devices())
    rooms      = len(db.get_rooms())

    return jsonify({
        "status":           "ok" if alive else "degraded",
        "ha_connected":     alive,
        "ha_url":           os.environ.get("HA_URL"),
        "registered_devices": registered,
        "rooms":            rooms,
        "version":          "1.0.0",
    }), 200 if alive else 503

# ── Discovery ──────────────────────────────────────────────────────────

@app.get("/api/v1/discover")
def discover():
    """
    All devices HA knows about, normalized.
    Includes registered=true/false so you can see what's in the twin.
    Query params:
      domain=light        filter by domain (light, switch, sensor, etc.)
      unregistered=true   only show devices not yet in the twin
    """
    try:
        client      = ha()
        domain      = request.args.get("domain")
        unreg_only  = request.args.get("unregistered", "").lower() == "true"
        registered  = {d["entity_id"] for d in db.get_all_devices()}
        raw         = client.get_discovered_devices(domain_filter=domain)
        twin_meta   = {d["entity_id"]: d for d in db.get_all_devices()}

        result = {}
        for d, states in raw.items():
            devices = []
            for s in states:
                eid  = s["entity_id"]
                if unreg_only and eid in registered:
                    continue
                meta = twin_meta.get(eid)
                devices.append(client.normalize(s, meta))
            if devices:
                result[d] = devices

        total = sum(len(v) for v in result.values())
        return jsonify({"total": total, "domains": result})
    except HAError as e:
        return err(str(e), 502)

@app.get("/api/v1/discover/domains")
def discover_domains():
    """Summary of all available domains with device counts."""
    try:
        raw = ha().get_discovered_devices()
        registered = {d["entity_id"] for d in db.get_all_devices()}
        return jsonify({
            d: {
                "count":      len(states),
                "registered": sum(1 for s in states if s["entity_id"] in registered),
            }
            for d, states in sorted(raw.items())
        })
    except HAError as e:
        return err(str(e), 502)

# ── Single device ──────────────────────────────────────────────────────

@app.get("/api/v1/devices/<path:entity_id>")
def get_device(entity_id):
    """Live state + twin metadata for one device."""
    try:
        state = ha().get_state(entity_id)
        meta  = db.get_device(entity_id)
        return jsonify(ha().normalize(state, meta))
    except HAError as e:
        return err(str(e), 502)

@app.post("/api/v1/devices/<path:entity_id>/control")
def control_device(entity_id):
    """
    Control any HA entity.

    Body: { "action": "turn_on", ...service_data }

    Examples:
      Turn on:           { "action": "turn_on" }
      Set brightness:    { "action": "turn_on", "brightness_pct": 70 }
      Set color:         { "action": "turn_on", "rgb_color": [255, 100, 0] }
      Set color temp:    { "action": "turn_on", "color_temp_kelvin": 4000 }
      Turn off:          { "action": "turn_off" }
      Toggle:            { "action": "toggle" }
      Set cover pos:     { "action": "set_cover_position", "position": 50 }
      Set climate temp:  { "action": "set_temperature", "temperature": 22 }
    """
    try:
        body   = request.get_json() or {}
        action = body.pop("action", None)
        if not action:
            return err("'action' is required")

        domain = entity_id.split(".")[0]
        client = ha()
        client.call_service(domain, action, {"entity_id": entity_id, **body})

        # Return fresh state after action
        state = client.get_state(entity_id)
        meta  = db.get_device(entity_id)
        return jsonify(client.normalize(state, meta))
    except HAError as e:
        return err(str(e), 502)

# ── Twin registry ──────────────────────────────────────────────────────
# This is what makes it a "digital twin" vs just a HA proxy.
# Registered devices have rooms, 3D positions, and custom metadata.

@app.get("/api/v1/twin/devices")
def list_twin_devices():
    """
    All registered twin devices with live HA state.
    These are the devices that appear in your 3D house model.
    """
    try:
        client   = ha()
        all_meta = db.get_all_devices()
        result   = []
        for meta in all_meta:
            try:
                state = client.get_state(meta["entity_id"])
                result.append(client.normalize(state, meta))
            except HAError:
                # Device registered but HA can't reach it right now
                result.append({
                    "entity_id": meta["entity_id"],
                    "domain":    meta["domain"],
                    "name":      meta.get("display_name", meta["entity_id"]),
                    "state":     "unavailable",
                    "registered": True,
                    **meta,
                })
        return jsonify({"count": len(result), "devices": result})
    except HAError as e:
        return err(str(e), 502)

@app.post("/api/v1/twin/devices")
def register_device():
    """
    Register a device into the twin.

    This is called when you pair a new Zigbee device and want it
    to appear in your 3D house model.

    Body:
    {
      "entity_id":    "light.bedroom_lamp",    ← required
      "room_id":      "bedroom",               ← optional (assign to room)
      "position_3d":  {"x": 1.2, "y": 2.4, "z": 0.0},  ← optional 3D coords
      "display_name": "Bedside Lamp",          ← optional override of HA name
      "notes":        "IKEA Tradfri E27"       ← optional
    }
    """
    body      = request.get_json() or {}
    entity_id = body.get("entity_id")
    if not entity_id:
        return err("'entity_id' is required")

    # Verify the device actually exists in HA
    try:
        state = ha().get_state(entity_id)
    except HAError as e:
        return err(f"Device not found in HA: {e}", 404)

    domain = entity_id.split(".")[0]
    meta   = db.register_device(
        entity_id    = entity_id,
        domain       = domain,
        display_name = body.get("display_name"),
        room_id      = body.get("room_id"),
        position_3d  = body.get("position_3d"),
        notes        = body.get("notes"),
    )
    return ok(ha().normalize(state, meta)), 201

@app.put("/api/v1/twin/devices/<path:entity_id>")
def update_device(entity_id):
    """
    Update twin metadata for a registered device.
    Use this to move a device to a different room or update its 3D position.

    Body (all optional):
    {
      "room_id":      "living_room",
      "position_3d":  {"x": 2.5, "y": 2.4, "z": 1.0},
      "display_name": "Floor Lamp",
      "notes":        "Philips Hue A19"
    }
    """
    if not db.get_device(entity_id):
        return err("Device not registered — POST /api/v1/twin/devices first", 404)

    body = request.get_json() or {}
    meta = db.update_device(
        entity_id,
        display_name = body.get("display_name"),
        room_id      = body.get("room_id"),
        position_3d  = body.get("position_3d"),
        notes        = body.get("notes"),
    )
    try:
        state = ha().get_state(entity_id)
        return ok(ha().normalize(state, meta))
    except HAError:
        return ok(meta)

@app.delete("/api/v1/twin/devices/<path:entity_id>")
def unregister_device(entity_id):
    """
    Remove a device from the twin.
    Does NOT delete it from HA — just removes it from your 3D model.
    """
    if not db.unregister_device(entity_id):
        return err("Device not registered", 404)
    return ok(message=f"{entity_id} removed from twin")

# ── Rooms ──────────────────────────────────────────────────────────────

@app.get("/api/v1/rooms")
def list_rooms():
    """All rooms with device counts."""
    rooms      = db.get_rooms()
    all_devs   = db.get_all_devices()
    counts     = {}
    for d in all_devs:
        if d.get("room_id"):
            counts[d["room_id"]] = counts.get(d["room_id"], 0) + 1
    for r in rooms:
        r["device_count"] = counts.get(r["id"], 0)
    return jsonify(rooms)

@app.post("/api/v1/rooms")
def create_room():
    """
    Create a room.

    Body:
    {
      "name":  "Living Room",   ← required
      "floor": 1,               ← optional, default 1
      "color": "#f59e0b",       ← optional, for 3D model
      "notes": ""               ← optional
    }
    id is auto-derived from name ("Living Room" → "living_room")
    """
    body = request.get_json() or {}
    name = body.get("name", "").strip()
    if not name:
        return err("'name' is required")

    room_id = body.get("id") or slugify(name)

    if db.get_room(room_id):
        return err(f"Room '{room_id}' already exists. Use PUT to update.", 409)

    room = db.create_room(
        room_id = room_id,
        name    = name,
        floor   = body.get("floor", 1),
        color   = body.get("color"),
        notes   = body.get("notes"),
    )
    return ok(room), 201

@app.put("/api/v1/rooms/<room_id>")
def update_room(room_id):
    """Update room metadata."""
    if not db.get_room(room_id):
        return err("Room not found", 404)
    body = request.get_json() or {}
    room = db.update_room(room_id, **body)
    return ok(room)

@app.delete("/api/v1/rooms/<room_id>")
def delete_room(room_id):
    """
    Delete a room. Devices in the room are unassigned (not deleted).
    """
    if not db.delete_room(room_id):
        return err("Room not found", 404)
    return ok(message=f"Room '{room_id}' deleted. Devices have been unassigned.")

@app.get("/api/v1/rooms/<room_id>")
def get_room(room_id):
    """Room details + all registered devices in it with live state."""
    room = db.get_room(room_id)
    if not room:
        return err("Room not found", 404)

    try:
        client   = ha()
        devices  = db.get_all_devices(room_id=room_id)
        result   = []
        for meta in devices:
            try:
                state = client.get_state(meta["entity_id"])
                result.append(client.normalize(state, meta))
            except HAError:
                result.append({**meta, "state": "unavailable"})
        room["devices"]      = result
        room["device_count"] = len(result)
    except HAError:
        room["devices"]      = []
        room["device_count"] = 0

    return jsonify(room)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
