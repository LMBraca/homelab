"""
SQLite persistence layer for the digital twin.
Stores rooms and registered devices.
HA is the source of truth for live state — this only stores twin metadata.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/app/data/twin.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    floor       INTEGER DEFAULT 1,
    color       TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    entity_id       TEXT PRIMARY KEY,
    domain          TEXT NOT NULL,
    display_name    TEXT,
    room_id         TEXT REFERENCES rooms(id) ON DELETE SET NULL,
    position_3d     TEXT,           -- JSON: {"x": 1.0, "y": 2.4, "z": 0.5}
    notes           TEXT,
    registered_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    if "position_3d" in d and d["position_3d"]:
        d["position_3d"] = json.loads(d["position_3d"])
    return d

# ── Rooms ──────────────────────────────────────────────────────────────

def get_rooms():
    with get_db() as db:
        rows = db.execute("SELECT * FROM rooms ORDER BY floor, name").fetchall()
        return [row_to_dict(r) for r in rows]

def get_room(room_id):
    with get_db() as db:
        return row_to_dict(db.execute(
            "SELECT * FROM rooms WHERE id = ?", (room_id,)
        ).fetchone())

def create_room(room_id, name, floor=1, color=None, notes=None):
    t = now()
    with get_db() as db:
        db.execute(
            "INSERT INTO rooms (id, name, floor, color, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (room_id, name, floor, color, notes, t, t)
        )
    return get_room(room_id)

def update_room(room_id, **fields):
    allowed = {"name", "floor", "color", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_room(room_id)
    updates["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in updates)
    with get_db() as db:
        db.execute(f"UPDATE rooms SET {cols} WHERE id = ?",
                   (*updates.values(), room_id))
    return get_room(room_id)

def delete_room(room_id):
    with get_db() as db:
        affected = db.execute(
            "DELETE FROM rooms WHERE id = ?", (room_id,)
        ).rowcount
    return affected > 0

# ── Devices ────────────────────────────────────────────────────────────

def get_device(entity_id):
    with get_db() as db:
        return row_to_dict(db.execute(
            "SELECT * FROM devices WHERE entity_id = ?", (entity_id,)
        ).fetchone())

def get_all_devices(room_id=None):
    with get_db() as db:
        if room_id:
            rows = db.execute(
                "SELECT * FROM devices WHERE room_id = ? ORDER BY domain, entity_id",
                (room_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM devices ORDER BY domain, entity_id"
            ).fetchall()
        return [row_to_dict(r) for r in rows]

def register_device(entity_id, domain, display_name=None,
                    room_id=None, position_3d=None, notes=None):
    t = now()
    pos = json.dumps(position_3d) if position_3d else None
    with get_db() as db:
        db.execute("""
            INSERT INTO devices
                (entity_id, domain, display_name, room_id, position_3d, notes, registered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                display_name = excluded.display_name,
                room_id      = excluded.room_id,
                position_3d  = excluded.position_3d,
                notes        = excluded.notes,
                updated_at   = excluded.updated_at
        """, (entity_id, domain, display_name, room_id, pos, notes, t, t))
    return get_device(entity_id)

def update_device(entity_id, **fields):
    allowed = {"display_name", "room_id", "position_3d", "notes"}
    # Only update fields that were explicitly provided (non-None).
    # None means "not present in request body" — do NOT overwrite existing values.
    # This prevents PUT /twin/devices/<id> with only position_3d from wiping room_id.
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "position_3d" in updates:
        updates["position_3d"] = json.dumps(updates["position_3d"])
    if not updates:
        return get_device(entity_id)
    updates["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in updates)
    with get_db() as db:
        db.execute(f"UPDATE devices SET {cols} WHERE entity_id = ?",
                   (*updates.values(), entity_id))
    return get_device(entity_id)

def unregister_device(entity_id):
    with get_db() as db:
        return db.execute(
            "DELETE FROM devices WHERE entity_id = ?", (entity_id,)
        ).rowcount > 0
