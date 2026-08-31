"""Parameterized SQLite commands for vehicles, parking slots, active parking, and results."""
import json
import re
from datetime import datetime, timezone
from .database import get_connection

# ─────────────────────────────────────────────────────────────
# Plate normalisation
# ─────────────────────────────────────────────────────────────

def normalise_plate(plate: str) -> str:
    """Uppercase, strip spaces, hyphens, and all non-alphanumeric chars."""
    return re.sub(r"[^A-Z0-9]", "", plate.upper())

# ─────────────────────────────────────────────────────────────
# Vehicle CRUD
# ─────────────────────────────────────────────────────────────

def list_vehicles():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM vehicle_records ORDER BY owner_name, plate").fetchall()
    return [dict(row) for row in rows]

def get_vehicle(plate: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM vehicle_records WHERE plate = ?", (normalise_plate(plate),)).fetchone()
    return dict(row) if row else None

def create_vehicle(plate: str, owner_name: str, category: str, permit_tier: int = 4):
    plate = normalise_plate(plate)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO vehicle_records (plate, owner_name, category, permit_tier) VALUES (?, ?, ?, ?)",
            (plate, owner_name.strip(), category, permit_tier),
        )
        row = conn.execute("SELECT * FROM vehicle_records WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)

def update_vehicle(plate: str, owner_name: str | None, category: str | None, permit_tier: int | None = None):
    current = get_vehicle(plate)
    if not current:
        return None
    name = owner_name.strip() if owner_name is not None else current["owner_name"]
    vehicle_category = category or current["category"]
    tier = permit_tier if permit_tier is not None else current["permit_tier"]
    with get_connection() as conn:
        conn.execute(
            "UPDATE vehicle_records SET owner_name = ?, category = ?, permit_tier = ?, updated_at = CURRENT_TIMESTAMP WHERE plate = ?",
            (name, vehicle_category, tier, normalise_plate(plate)),
        )
    return get_vehicle(plate)

def delete_vehicle(plate: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM vehicle_records WHERE plate = ?", (normalise_plate(plate),))
    return cursor.rowcount > 0

def vehicle_for_plate(plate: str):
    """Return owner info for a plate; defaults to Visitor if unregistered."""
    vehicle = get_vehicle(plate)
    if vehicle:
        return {
            "studentName": vehicle["owner_name"],
            "category": vehicle["category"],
            "permit_tier": vehicle["permit_tier"],
        }
    return {"studentName": "Campus Visitor", "category": "Visitor", "permit_tier": 5}

# ─────────────────────────────────────────────────────────────
# Parking Slots
# ─────────────────────────────────────────────────────────────

def list_slots():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM parking_slots ORDER BY slot_id").fetchall()
    return [_enrich_slot(dict(row)) for row in rows]

def get_slot(slot_id: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM parking_slots WHERE slot_id = ?", (slot_id,)).fetchone()
    return _enrich_slot(dict(row)) if row else None

def _enrich_slot(row: dict) -> dict:
    """Parse directions JSON for API consumers."""
    try:
        row["directions_parsed"] = json.loads(row.get("directions") or "[]")
    except (json.JSONDecodeError, TypeError):
        row["directions_parsed"] = []
    return row

def update_slot_info(slot_id: str, path_description: str, directions: list, floor: str, section: str) -> dict | None:
    """Admin: update per-slot navigation details."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE parking_slots
               SET path_description = ?, directions = ?, floor = ?, section = ?
               WHERE slot_id = ?""",
            (path_description, json.dumps(directions), floor, section, slot_id),
        )
    return get_slot(slot_id)

def find_available_slot(permit_tier: int):
    """Find the first available slot that the permit tier can access.

    Tier 1 (VIP) can park anywhere; lower tier # = higher privilege.
    Tier 5 (Visitor) can only park in visitor slots.
    Returns full slot info including navigation details.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT slot_id, zone, path_description, directions, floor, section
               FROM parking_slots
               WHERE status = 'available' AND min_permit_tier >= ?
               ORDER BY min_permit_tier DESC, slot_id ASC
               LIMIT 1""",
            (permit_tier,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["directions_parsed"] = json.loads(result.get("directions") or "[]")
    except (json.JSONDecodeError, TypeError):
        result["directions_parsed"] = []
    return result

def occupy_slot(slot_id: str, plate: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE parking_slots SET status = 'occupied', occupied_by = ? WHERE slot_id = ?",
            (plate, slot_id),
        )

def release_slot(slot_id: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE parking_slots SET status = 'available', occupied_by = NULL WHERE slot_id = ?",
            (slot_id,),
        )

# ─────────────────────────────────────────────────────────────
# Active Parking (DB-persisted — survives restarts)
# ─────────────────────────────────────────────────────────────

def get_active_vehicle(plate: str):
    """Check if a vehicle is currently parked."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM active_parking WHERE plate = ?", (normalise_plate(plate),)).fetchone()
    return dict(row) if row else None

def list_active_parking():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM active_parking ORDER BY entry_time DESC").fetchall()
    return [dict(row) for row in rows]

def park_vehicle(plate: str, slot_id: str, owner_name: str, category: str, permit_tier: int):
    """Record a vehicle as actively parked and mark its slot occupied."""
    plate = normalise_plate(plate)
    occupy_slot(slot_id, plate)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO active_parking (plate, slot_id, owner_name, category, permit_tier)
               VALUES (?, ?, ?, ?, ?)""",
            (plate, slot_id, owner_name, category, permit_tier),
        )

def verify_vehicle_parked(plate: str) -> bool:
    """Mark a vehicle's parking as verified by the parking camera."""
    plate = normalise_plate(plate)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE active_parking SET verified = 1 WHERE plate = ?",
            (plate,),
        )
    return cursor.rowcount > 0

def exit_vehicle(plate: str):
    """Remove vehicle from active parking, release its slot, and save to history.
    Returns the history record or None if vehicle wasn't parked."""
    plate = normalise_plate(plate)
    active = get_active_vehicle(plate)
    if not active:
        return None

    # Calculate duration
    entry = datetime.fromisoformat(active["entry_time"].replace(" ", "T"))
    now = datetime.now(timezone.utc)
    entry_utc = entry.replace(tzinfo=timezone.utc) if entry.tzinfo is None else entry
    duration = max(0, int((now - entry_utc).total_seconds() / 60))

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO parking_history (plate, slot_id, owner_name, category, permit_tier, entry_time, exit_time, duration_minutes, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (plate, active["slot_id"], active["owner_name"], active["category"],
             active["permit_tier"], active["entry_time"],
             now.isoformat(), duration, "system"),
        )
        conn.execute("DELETE FROM active_parking WHERE plate = ?", (plate,))

    release_slot(active["slot_id"])

    return {
        "plate": plate,
        "slot_id": active["slot_id"],
        "owner_name": active["owner_name"],
        "category": active["category"],
        "entry_time": active["entry_time"],
        "duration_minutes": duration,
    }

def count_occupied():
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM active_parking").fetchone()
    return row[0] if row else 0

# ─────────────────────────────────────────────────────────────
# Parking Queue
# ─────────────────────────────────────────────────────────────

def queue_add(plate: str, owner_name: str, category: str, permit_tier: int) -> dict | None:
    """Add a vehicle to the waiting queue. Returns queue entry or None if already queued."""
    plate = normalise_plate(plate)
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO parking_queue (plate, owner_name, category, permit_tier)
                   VALUES (?, ?, ?, ?)""",
                (plate, owner_name, category, permit_tier),
            )
            row = conn.execute("SELECT * FROM parking_queue WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)
    except Exception:
        return None  # already in queue (UNIQUE constraint)

def queue_get_waiting() -> list[dict]:
    """Return all vehicles currently waiting in queue, ordered by join time."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM parking_queue WHERE status = 'waiting' ORDER BY joined_at ASC"
        ).fetchall()
    return [dict(row) for row in rows]

def queue_get_position(plate: str) -> int:
    """Return 1-based queue position for a plate, or 0 if not in queue."""
    plate = normalise_plate(plate)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT plate FROM parking_queue WHERE status = 'waiting' ORDER BY joined_at ASC"
        ).fetchall()
    plates = [r["plate"] for r in rows]
    try:
        return plates.index(plate) + 1
    except ValueError:
        return 0

def queue_remove(plate: str, status: str = "abandoned") -> bool:
    """Remove (or mark as assigned/abandoned) a vehicle from the queue."""
    plate = normalise_plate(plate)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE parking_queue SET status = ? WHERE plate = ? AND status = 'waiting'",
            (status, plate),
        )
    return cursor.rowcount > 0

def queue_assign_next(freed_slot_id: str) -> dict | None:
    """When a slot is freed, find the next eligible queued vehicle and assign it.

    Returns dict with {plate, owner_name, category, permit_tier, slot_info} or None.
    """
    with get_connection() as conn:
        # Get slot details to know its min_permit_tier
        slot_row = conn.execute(
            "SELECT min_permit_tier FROM parking_slots WHERE slot_id = ? AND status = 'available'",
            (freed_slot_id,),
        ).fetchone()
        if not slot_row:
            return None
        slot_min_tier = slot_row["min_permit_tier"]

        # Find the first queued vehicle whose permit_tier is <= slot_min_tier (eligible)
        next_vehicle = conn.execute(
            """SELECT * FROM parking_queue
               WHERE status = 'waiting' AND permit_tier <= ?
               ORDER BY joined_at ASC LIMIT 1""",
            (slot_min_tier,),
        ).fetchone()

    if not next_vehicle:
        return None

    v = dict(next_vehicle)
    slot_info = find_available_slot(v["permit_tier"])
    if not slot_info:
        return None

    # Park the vehicle
    park_vehicle(v["plate"], slot_info["slot_id"], v["owner_name"], v["category"], v["permit_tier"])
    queue_remove(v["plate"], status="assigned")

    return {
        "plate": v["plate"],
        "owner_name": v["owner_name"],
        "category": v["category"],
        "permit_tier": v["permit_tier"],
        "slot_info": slot_info,
    }

# ─────────────────────────────────────────────────────────────
# Parking History
# ─────────────────────────────────────────────────────────────

def list_history(limit: int = 50):
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM parking_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]

# ─────────────────────────────────────────────────────────────
# Results (live activity log)
# ─────────────────────────────────────────────────────────────

def add_result(result: dict):
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO parking_results (plate, owner_name, category, slot, direction, confidence, source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.get("plate_number", ""), result.get("studentName", "Visitor"), result.get("category", "Guest"),
             result.get("slot", ""), result.get("direction", ""), result.get("yolo_confidence", 0.0),
             result.get("source", "gate"), result.get("status", "GRANTED")),
        )
    result["id"] = cursor.lastrowid
    return result

def list_results(limit: int = 50):
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM parking_results ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [to_web_result(dict(row)) for row in rows]

def latest_result():
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM parking_results ORDER BY id DESC LIMIT 1").fetchone()
    return to_web_result(dict(row)) if row else None

def to_web_result(row: dict):
    plate = row["plate"]
    ocr_success = bool(plate and plate != "UNKNOWN")
    return {
        "id": row["id"],
        "success": True,
        "type": "parking_result",
        "plate_detected": True,
        "ocr_success": ocr_success,
        "plate_number": plate,
        "yolo_confidence": row["confidence"],
        "studentName": row["owner_name"],
        "category": row["category"],
        "slot": row["slot"],
        "direction": row["direction"],
        "source": row["source"],
        "status": str(row.get("status", "GRANTED")).upper(),
        "timestamp": row["created_at"].replace(" ", "T") + "+00:00",
    }

# ─────────────────────────────────────────────────────────────
# System Logs
# ─────────────────────────────────────────────────────────────

def list_logs(limit: int = 100, level_filter: str | None = None, plate_filter: str | None = None) -> list[dict]:
    """Return system logs, most recent first."""
    query = "SELECT * FROM system_logs WHERE 1=1"
    params: list = []
    if level_filter:
        query += " AND level = ?"
        params.append(level_filter.upper())
    if plate_filter:
        query += " AND plate LIKE ?"
        params.append(f"%{normalise_plate(plate_filter)}%")
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]

def get_log_stats() -> dict:
    """Return count of logs per level for the current day."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT level, COUNT(*) as count FROM system_logs WHERE DATE(created_at) = DATE('now') GROUP BY level"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM system_logs").fetchone()[0]
    counts = {row["level"]: row["count"] for row in rows}
    return {
        "total": total,
        "today_debug":    counts.get("DEBUG", 0),
        "today_info":     counts.get("INFO", 0),
        "today_warn":     counts.get("WARN", 0),
        "today_error":    counts.get("ERROR", 0),
        "today_critical": counts.get("CRITICAL", 0),
    }

# ─────────────────────────────────────────────────────────────
# Dashboard Statistics
# ─────────────────────────────────────────────────────────────

def get_dashboard_stats():
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM parking_slots").fetchone()[0]
        occupied = conn.execute("SELECT COUNT(*) FROM parking_slots WHERE status = 'occupied'").fetchone()[0]
        available = total - occupied
        active_count = conn.execute("SELECT COUNT(*) FROM active_parking").fetchone()[0]
        today_entries = conn.execute(
            "SELECT COUNT(*) FROM parking_results WHERE DATE(created_at) = DATE('now') AND status = 'granted'"
        ).fetchone()[0]
        today_exits = conn.execute(
            "SELECT COUNT(*) FROM parking_results WHERE DATE(created_at) = DATE('now') AND status = 'exited'"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM parking_results WHERE DATE(created_at) = DATE('now') AND status IN ('already_parked', 'no_slot', 'rejected')"
        ).fetchone()[0]
        queue_count = conn.execute(
            "SELECT COUNT(*) FROM parking_queue WHERE status = 'waiting'"
        ).fetchone()[0]
    return {
        "total_slots": total,
        "occupied": occupied,
        "available": available,
        "active_vehicles": active_count,
        "today_entries": today_entries,
        "today_exits": today_exits,
        "today_rejected": rejected,
        "queue_waiting": queue_count,
    }

# ─────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────

def get_settings():
    with get_connection() as conn:
        rows = conn.execute("SELECT setting_key, setting_value FROM app_settings").fetchall()
    values = {row["setting_key"]: row["setting_value"] for row in rows}
    return {"campus_name": values.get("campus_name", "Smart Campus"), "total_slots": int(values.get("total_slots", 50))}

def save_settings(campus_name: str, total_slots: int):
    with get_connection() as conn:
        conn.execute("INSERT INTO app_settings VALUES ('campus_name', ?, CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=CURRENT_TIMESTAMP", (campus_name.strip(),))
        conn.execute("INSERT INTO app_settings VALUES ('total_slots', ?, CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=CURRENT_TIMESTAMP", (str(total_slots),))
    return get_settings()
