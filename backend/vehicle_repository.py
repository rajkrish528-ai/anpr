"""Parameterized SQLite commands for vehicles, parking slots, active parking, and results."""
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
    return [dict(row) for row in rows]

def find_available_slot(permit_tier: int):
    """Find the first available slot that the permit tier can access.
    
    Tier 1 can park anywhere. Tier 4 can only park in tier-4+ zones.
    Visitor (tier 5) can only park in visitor slots.
    """
    with get_connection() as conn:
        # Find a slot where:
        # - status is 'available'
        # - the slot's min_permit_tier >= the vehicle's tier 
        #   (lower tier number = higher priority, can access more zones)
        row = conn.execute(
            """SELECT slot_id, zone FROM parking_slots 
               WHERE status = 'available' AND min_permit_tier >= ?
               ORDER BY min_permit_tier DESC, slot_id ASC
               LIMIT 1""",
            (permit_tier,),
        ).fetchone()
    return dict(row) if row else None

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
    # entry_time from SQLite is in UTC (CURRENT_TIMESTAMP)
    entry_utc = entry.replace(tzinfo=timezone.utc) if entry.tzinfo is None else entry
    duration = max(0, int((now - entry_utc).total_seconds() / 60))

    with get_connection() as conn:
        # Save to history
        conn.execute(
            """INSERT INTO parking_history (plate, slot_id, owner_name, category, permit_tier, entry_time, exit_time, duration_minutes, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (plate, active["slot_id"], active["owner_name"], active["category"],
             active["permit_tier"], active["entry_time"],
             now.isoformat(), duration, "system"),
        )
        # Remove from active
        conn.execute("DELETE FROM active_parking WHERE plate = ?", (plate,))

    # Release slot
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
            (result.get("plate_number", ""), result.get("studentName", "Visitor"), result.get("category", "Guest"), result.get("slot", ""),
             result.get("direction", ""), result.get("yolo_confidence", 0.0), result.get("source", "gate"),
             result.get("status", "GRANTED")),
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
    return {
        "total_slots": total,
        "occupied": occupied,
        "available": available,
        "active_vehicles": active_count,
        "today_entries": today_entries,
        "today_exits": today_exits,
        "today_rejected": rejected,
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
