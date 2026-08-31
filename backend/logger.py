"""
Centralized structured system logger for Smart Parking.

Usage:
    from backend.logger import log, EventType, LogLevel

    log(LogLevel.INFO, EventType.SLOT_ASSIGNED,
        "Slot S12 assigned to MH12AB1234", plate="MH12AB1234",
        slot_id="S12", category="Faculty", source="gate")
"""
import json
from datetime import datetime, timezone
from .database import get_connection

# ── ANSI colour codes for stdout ──────────────────────────────────────────────
_RESET  = "\033[0m"
_COLORS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARN":     "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
}


class LogLevel:
    DEBUG    = "DEBUG"
    INFO     = "INFO"
    WARN     = "WARN"
    ERROR    = "ERROR"
    CRITICAL = "CRITICAL"


class EventType:
    # Detection events
    PLATE_DETECTED   = "PLATE_DETECTED"
    PLATE_OCR_FAILED = "PLATE_OCR_FAILED"
    NO_PLATE         = "NO_PLATE"

    # Parking lifecycle
    SLOT_ASSIGNED    = "SLOT_ASSIGNED"
    SLOT_VERIFIED    = "SLOT_VERIFIED"    # parking camera confirmed
    VEHICLE_ENTERED  = "VEHICLE_ENTERED"
    VEHICLE_EXITED   = "VEHICLE_EXITED"
    ALREADY_PARKED   = "ALREADY_PARKED"

    # Slot states
    NO_SLOT          = "NO_SLOT"          # parking full

    # Queue events
    QUEUE_JOINED     = "QUEUE_JOINED"
    QUEUE_ASSIGNED   = "QUEUE_ASSIGNED"
    QUEUE_ABANDONED  = "QUEUE_ABANDONED"

    # Admin actions
    ADMIN_ACTION     = "ADMIN_ACTION"
    SLOT_INFO_UPDATED = "SLOT_INFO_UPDATED"

    # System
    SYSTEM_START     = "SYSTEM_START"
    CAMERA_ERROR     = "CAMERA_ERROR"
    SYSTEM_ERROR     = "SYSTEM_ERROR"


def log(
    level: str,
    event_type: str,
    message: str,
    plate: str | None = None,
    slot_id: str | None = None,
    category: str | None = None,
    source: str | None = None,
    extra: dict | None = None,
) -> int | None:
    """Write a structured log entry to the system_logs table and stdout.

    Returns the new log row id, or None on failure.
    """
    now = datetime.now(timezone.utc)
    extra_json = json.dumps(extra) if extra else None

    # ── stdout ────────────────────────────────────────────────────────────────
    color = _COLORS.get(level, "")
    ts    = now.strftime("%H:%M:%S")
    parts = [f"[{ts}]", f"{color}[{level}]{_RESET}", f"[{event_type}]", message]
    if plate:   parts.append(f"plate={plate}")
    if slot_id: parts.append(f"slot={slot_id}")
    if source:  parts.append(f"src={source}")
    print(" ".join(parts))

    # ── database ──────────────────────────────────────────────────────────────
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO system_logs
                   (level, event_type, message, plate, slot_id, category, source, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (level, event_type, message, plate, slot_id, category, source, extra_json),
            )
            return cursor.lastrowid
    except Exception as exc:
        print(f"[LOGGER ERROR] Failed to write log to DB: {exc}")
        return None
