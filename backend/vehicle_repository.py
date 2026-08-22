"""Parameterized SQLite commands for vehicles and parking results."""
from datetime import datetime, timezone
from .database import get_connection

def normalise_plate(plate: str) -> str:
    return "".join(plate.upper().split())

def list_vehicles():
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM vehicle_records ORDER BY owner_name, plate").fetchall()
    return [dict(row) for row in rows]

def get_vehicle(plate: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM vehicle_records WHERE plate = ?", (normalise_plate(plate),)).fetchone()
    return dict(row) if row else None

def create_vehicle(plate: str, owner_name: str, category: str):
    plate = normalise_plate(plate)
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO vehicle_records (plate, owner_name, category) VALUES (?, ?, ?)",
            (plate, owner_name.strip(), category),
        )
        row = connection.execute("SELECT * FROM vehicle_records WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)

def update_vehicle(plate: str, owner_name: str | None, category: str | None):
    current = get_vehicle(plate)
    if not current:
        return None
    name = owner_name.strip() if owner_name is not None else current["owner_name"]
    vehicle_category = category or current["category"]
    with get_connection() as connection:
        connection.execute(
            "UPDATE vehicle_records SET owner_name = ?, category = ?, updated_at = CURRENT_TIMESTAMP WHERE plate = ?",
            (name, vehicle_category, normalise_plate(plate)),
        )
    return get_vehicle(plate)

def delete_vehicle(plate: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM vehicle_records WHERE plate = ?", (normalise_plate(plate),))
    return cursor.rowcount > 0

def add_result(result: dict):
    with get_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO parking_results (plate, owner_name, category, slot, direction, confidence, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (result["plate"], result["studentName"], result["category"], result["slot"], result["direction"], result["confidence"], result["source"]),
        )
    result["id"] = cursor.lastrowid
    return result

def list_results(limit: int = 50):
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM parking_results ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [to_web_result(dict(row)) for row in rows]

def latest_result():
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM parking_results ORDER BY id DESC LIMIT 1").fetchone()
    return to_web_result(dict(row)) if row else None

def to_web_result(row: dict):
    return {"id": row["id"], "type": "parking_result", "plate": row["plate"], "studentName": row["owner_name"], "category": row["category"], "slot": row["slot"], "direction": row["direction"], "confidence": row["confidence"], "source": row["source"], "timestamp": row["created_at"].replace(" ", "T") + "+00:00"}

def vehicle_for_plate(plate: str):
    vehicle = get_vehicle(plate)
    if vehicle:
        return {"studentName": vehicle["owner_name"], "category": vehicle["category"]}
    return {"studentName": "Campus Visitor", "category": "Visitor"}

def get_settings():
    with get_connection() as connection:
        rows = connection.execute("SELECT setting_key, setting_value FROM app_settings").fetchall()
    values = {row["setting_key"]: row["setting_value"] for row in rows}
    return {"campus_name": values.get("campus_name", "Smart Campus"), "total_slots": int(values.get("total_slots", 50))}

def save_settings(campus_name: str, total_slots: int):
    with get_connection() as connection:
        connection.execute("INSERT INTO app_settings VALUES ('campus_name', ?, CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=CURRENT_TIMESTAMP", (campus_name.strip(),))
        connection.execute("INSERT INTO app_settings VALUES ('total_slots', ?, CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=CURRENT_TIMESTAMP", (str(total_slots),))
    return get_settings()
