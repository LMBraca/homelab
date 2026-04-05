#!/usr/bin/env python3
"""
seed.py — Seeds the digital twin database with rooms and simulated devices.

Run this once after HA is up and the digital-twin-api container is running:
    python3 seed.py

It is safe to run multiple times — rooms and devices use upsert logic.
"""

import json
import urllib.request
import urllib.error

API = "http://localhost:8000"


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        res = urllib.request.urlopen(req, timeout=5)
        return json.loads(res.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 409:
            print(f"  (already exists, skipping)")
            return None
        print(f"  ERROR {e.code}: {body}")
        return None


def put(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, method="PUT",
        headers={"Content-Type": "application/json"}
    )
    try:
        res = urllib.request.urlopen(req, timeout=5)
        return json.loads(res.read())
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()}")
        return None


# ── Rooms ─────────────────────────────────────────────────────
ROOMS = [
    # Floor 1
    {"id": "living_room",       "name": "Living Room",       "floor": 1, "color": "#6366f1"},
    {"id": "kitchen",           "name": "Kitchen",           "floor": 1, "color": "#f59e0b"},
    {"id": "front_door",        "name": "Front Door",        "floor": 1, "color": "#22c55e"},
    {"id": "staircase",         "name": "Staircase",         "floor": 1, "color": "#94a3b8"},
    {"id": "estancia",          "name": "Estancia",          "floor": 1, "color": "#06b6d4"},
    {"id": "bathroom_1",        "name": "Bathroom 1",        "floor": 1, "color": "#3b82f6"},
    # Floor 2
    {"id": "bedroom_principal", "name": "Bedroom Principal", "floor": 2, "color": "#8b5cf6"},
    {"id": "bedroom_guest",     "name": "Bedroom Guest",     "floor": 2, "color": "#ec4899"},
    {"id": "bathroom_2",        "name": "Bathroom 2",        "floor": 2, "color": "#3b82f6"},
    {"id": "bathroom_3",        "name": "Bathroom 3",        "floor": 2, "color": "#3b82f6"},
]

# ── Devices ───────────────────────────────────────────────────
DEVICES = [
    # Living Room
    {"entity_id": "light.living_room",
     "room_id": "living_room", "display_name": "Living Room Light",
     "notes": "SIM — replace with Zigbee bulb",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "binary_sensor.living_room_motion",
     "room_id": "living_room", "display_name": "Living Room Motion",
     "notes": "SIM — replace with Zigbee PIR (e.g. Aqara P1)",
     "position_3d": {"x": 1.5, "y": 2.2, "z": 1.5}},

    {"entity_id": "sensor.living_room_tv",
     "room_id": "living_room", "display_name": "Living Room TV",
     "notes": "SIM — replace with Android TV / Apple TV integration",
     "position_3d": {"x": -2.0, "y": 1.0, "z": 0.0}},

    # Kitchen
    {"entity_id": "light.kitchen",
     "room_id": "kitchen", "display_name": "Kitchen Light",
     "notes": "SIM — replace with Zigbee bulb",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "binary_sensor.kitchen_motion",
     "room_id": "kitchen", "display_name": "Kitchen Motion",
     "notes": "SIM — replace with Zigbee PIR",
     "position_3d": {"x": 1.0, "y": 2.2, "z": 1.0}},

    # Front Door
    {"entity_id": "binary_sensor.front_door_contact",
     "room_id": "front_door", "display_name": "Front Door Contact",
     "notes": "SIM — replace with Zigbee door sensor (e.g. Aqara D1)",
     "position_3d": {"x": 0.1, "y": 1.5, "z": 0.0}},

    {"entity_id": "binary_sensor.front_door_motion",
     "room_id": "front_door", "display_name": "Front Door Motion",
     "notes": "SIM — replace with outdoor PIR or video doorbell",
     "position_3d": {"x": 0.0, "y": 2.0, "z": 0.5}},

    # Staircase
    {"entity_id": "light.staircase",
     "room_id": "staircase", "display_name": "Staircase Light",
     "notes": "SIM — replace with Zigbee bulb or LED strip",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "binary_sensor.staircase_motion",
     "room_id": "staircase", "display_name": "Staircase Motion",
     "notes": "SIM — replace with Zigbee PIR",
     "position_3d": {"x": 0.0, "y": 2.0, "z": 0.0}},

    # Bedroom Principal
    {"entity_id": "light.bedroom_principal",
     "room_id": "bedroom_principal", "display_name": "Bedroom Principal Light",
     "notes": "SIM — replace with Zigbee bulb",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "binary_sensor.bedroom_principal_motion",
     "room_id": "bedroom_principal", "display_name": "Bedroom Principal Motion",
     "notes": "SIM — replace with Zigbee PIR",
     "position_3d": {"x": 1.5, "y": 2.2, "z": 1.5}},

    # Bedroom Guest
    {"entity_id": "light.bedroom_guest",
     "room_id": "bedroom_guest", "display_name": "Bedroom Guest Light",
     "notes": "SIM — replace with Zigbee bulb",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "binary_sensor.bedroom_guest_motion",
     "room_id": "bedroom_guest", "display_name": "Bedroom Guest Motion",
     "notes": "SIM — replace with Zigbee PIR",
     "position_3d": {"x": 1.5, "y": 2.2, "z": 1.5}},

    # Bathroom 1
    {"entity_id": "light.bathroom_1",
     "room_id": "bathroom_1", "display_name": "Bathroom 1 Light",
     "notes": "SIM — replace with Zigbee bulb (IP44 rated)",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "sensor.bathroom_1_humidity",
     "room_id": "bathroom_1", "display_name": "Bathroom 1 Humidity",
     "notes": "SIM — replace with Zigbee temp/humidity sensor",
     "position_3d": {"x": 0.5, "y": 1.5, "z": 0.5}},

    # Bathroom 2
    {"entity_id": "light.bathroom_2",
     "room_id": "bathroom_2", "display_name": "Bathroom 2 Light",
     "notes": "SIM — replace with Zigbee bulb (IP44 rated)",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "sensor.bathroom_2_humidity",
     "room_id": "bathroom_2", "display_name": "Bathroom 2 Humidity",
     "notes": "SIM — replace with Zigbee temp/humidity sensor",
     "position_3d": {"x": 0.5, "y": 1.5, "z": 0.5}},

    # Bathroom 3
    {"entity_id": "light.bathroom_3",
     "room_id": "bathroom_3", "display_name": "Bathroom 3 Light",
     "notes": "SIM — replace with Zigbee bulb (IP44 rated)",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "sensor.bathroom_3_humidity",
     "room_id": "bathroom_3", "display_name": "Bathroom 3 Humidity",
     "notes": "SIM — replace with Zigbee temp/humidity sensor",
     "position_3d": {"x": 0.5, "y": 1.5, "z": 0.5}},

    # Estancia
    {"entity_id": "light.estancia",
     "room_id": "estancia", "display_name": "Estancia Light",
     "notes": "SIM — replace with Zigbee bulb",
     "position_3d": {"x": 0.0, "y": 2.4, "z": 0.0}},

    {"entity_id": "binary_sensor.estancia_motion",
     "room_id": "estancia", "display_name": "Estancia Motion",
     "notes": "SIM — replace with Zigbee PIR",
     "position_3d": {"x": 1.5, "y": 2.2, "z": 1.5}},
]


if __name__ == "__main__":
    print("=== Digital Twin Seed ===\n")

    print(f"Creating {len(ROOMS)} rooms...")
    for r in ROOMS:
        print(f"  Floor {r['floor']} — {r['name']} ({r['id']})", end=" ")
        result = post("/api/v1/rooms", r)
        if result:
            print("✓")

    print(f"\nRegistering {len(DEVICES)} devices...")
    for d in DEVICES:
        print(f"  {d['entity_id']} → {d['room_id']}", end=" ")
        result = post("/api/v1/twin/devices", d)
        if result:
            print("✓")

    print("\n=== Done ===")
    print("Verify at: http://100.87.156.88:8000/api/v1/rooms")
    print("           http://100.87.156.88:8000/api/v1/twin/devices")
