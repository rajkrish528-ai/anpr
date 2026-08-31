"""SQLite connection and table definitions for Smart Parking."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

DATABASE_PATH = Path(__file__).resolve().parent.parent / "parking.db"


@contextmanager
def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _safe_add_column(conn, table: str, column: str, col_def: str) -> None:
    """Add a column to a table only if it does not already exist (migration helper)."""
    try:
        conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def initialise_database():
    """Create persistent tables and seed initial data if they do not exist."""
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicle_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL UNIQUE,
                owner_name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Student',
                permit_tier INTEGER NOT NULL DEFAULT 4,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS parking_slots (
                slot_id TEXT PRIMARY KEY,
                zone TEXT NOT NULL DEFAULT 'General',
                min_permit_tier INTEGER NOT NULL DEFAULT 4,
                status TEXT NOT NULL DEFAULT 'available'
                    CHECK(status IN ('available', 'occupied')),
                occupied_by TEXT DEFAULT NULL,
                path_description TEXT NOT NULL DEFAULT '',
                directions TEXT NOT NULL DEFAULT '[]',
                floor TEXT NOT NULL DEFAULT 'Ground',
                section TEXT NOT NULL DEFAULT 'Main'
            );

            CREATE TABLE IF NOT EXISTS active_parking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL UNIQUE,
                slot_id TEXT NOT NULL,
                owner_name TEXT NOT NULL DEFAULT 'Unknown',
                category TEXT NOT NULL DEFAULT 'Visitor',
                permit_tier INTEGER NOT NULL DEFAULT 4,
                entry_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                verified INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (slot_id) REFERENCES parking_slots(slot_id)
            );

            CREATE TABLE IF NOT EXISTS parking_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL,
                slot_id TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                category TEXT NOT NULL,
                permit_tier INTEGER NOT NULL DEFAULT 4,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                duration_minutes INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'camera'
            );

            CREATE TABLE IF NOT EXISTS parking_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                category TEXT NOT NULL,
                slot TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'granted',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS camera_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL UNIQUE CHECK(role IN ('gate', 'parking')),
                device_index INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 0,
                detector TEXT NOT NULL DEFAULT 'yolov8_plate',
                ocr_engine TEXT NOT NULL DEFAULT 'tesseract',
                confidence_threshold REAL NOT NULL DEFAULT 0.40,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT OR IGNORE INTO camera_configs (role, device_index) VALUES ('gate', 0);
            INSERT OR IGNORE INTO camera_configs (role, device_index) VALUES ('parking', 0);

            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                admin_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE CASCADE
            );

            -- ── Structured system event log ───────────────────────────────────
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL DEFAULT 'INFO'
                    CHECK(level IN ('DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL')),
                event_type TEXT NOT NULL DEFAULT 'SYSTEM',
                message TEXT NOT NULL,
                plate TEXT DEFAULT NULL,
                slot_id TEXT DEFAULT NULL,
                category TEXT DEFAULT NULL,
                source TEXT DEFAULT NULL,
                extra TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- ── Waiting queue for vehicles when parking is full ───────────────
            CREATE TABLE IF NOT EXISTS parking_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL UNIQUE,
                owner_name TEXT NOT NULL DEFAULT 'Unknown',
                category TEXT NOT NULL DEFAULT 'Visitor',
                permit_tier INTEGER NOT NULL DEFAULT 5,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'waiting'
                    CHECK(status IN ('waiting', 'assigned', 'abandoned'))
            );

            INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES ('campus_name', 'Smart Campus');
            INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES ('total_slots', '50');
            """
        )

        # ── Migrate existing installs: permit_tier on vehicle_records ──
        _safe_add_column(connection, "vehicle_records", "permit_tier", "INTEGER NOT NULL DEFAULT 4")

        # ── Migrate existing installs: status on parking_results ──
        _safe_add_column(connection, "parking_results", "status", "TEXT NOT NULL DEFAULT 'granted'")

        # ── Migrate existing installs: nav columns on parking_slots ──
        _safe_add_column(connection, "parking_slots", "path_description", "TEXT NOT NULL DEFAULT ''")
        _safe_add_column(connection, "parking_slots", "directions", "TEXT NOT NULL DEFAULT '[]'")
        _safe_add_column(connection, "parking_slots", "floor", "TEXT NOT NULL DEFAULT 'Ground'")
        _safe_add_column(connection, "parking_slots", "section", "TEXT NOT NULL DEFAULT 'Main'")

        # ── Migrate existing installs: verified flag on active_parking ──
        _safe_add_column(connection, "active_parking", "verified", "INTEGER NOT NULL DEFAULT 0")

        # ── Seed parking slots (S1–S50) ──────────────────────────────────────
        existing = connection.execute("SELECT COUNT(*) FROM parking_slots").fetchone()[0]
        if existing == 0:
            slots = []
            for i in range(1, 51):
                if i <= 5:
                    zone, tier, floor_, section = "VIP Wing", 1, "Ground", "Block A"
                    path = "Enter main gate → turn right → proceed 20m to VIP Wing"
                    directions = '[{"action":"straight","landmark":"Main gate entry"},{"action":"right","landmark":"Security booth"},{"action":"arrive","landmark":"VIP Wing - Block A"}]'
                elif i <= 15:
                    zone, tier, floor_, section = "Faculty Block A", 2, "Ground", "Block B"
                    path = "Enter main gate → go straight → Faculty Block A on your left"
                    directions = '[{"action":"straight","landmark":"Main gate entry"},{"action":"left","landmark":"Admin building"},{"action":"arrive","landmark":"Faculty Block A"}]'
                elif i <= 25:
                    zone, tier, floor_, section = "Staff Block B", 3, "Level 1", "Block C"
                    path = "Enter main gate → take ramp to Level 1 → Staff Block B ahead"
                    directions = '[{"action":"straight","landmark":"Main gate entry"},{"action":"straight","landmark":"Ramp to Level 1"},{"action":"arrive","landmark":"Staff Block B"}]'
                elif i <= 45:
                    zone, tier, floor_, section = "Student Lot C", 4, "Level 2", "Block D"
                    path = "Enter main gate → proceed to Level 2 via ramp → Student Lot C"
                    directions = '[{"action":"straight","landmark":"Main gate entry"},{"action":"straight","landmark":"Level 2 ramp"},{"action":"left","landmark":"Student Lot signboard"},{"action":"arrive","landmark":"Student Lot C"}]'
                else:
                    zone, tier, floor_, section = "Visitor Lot D", 5, "Ground", "Block E"
                    path = "Enter main gate → turn left → Visitor Lot D at the far end"
                    directions = '[{"action":"straight","landmark":"Main gate entry"},{"action":"left","landmark":"Visitor parking sign"},{"action":"arrive","landmark":"Visitor Lot D"}]'
                slots.append((f"S{i}", zone, tier, "available", path, directions, floor_, section))

            connection.executemany(
                "INSERT INTO parking_slots (slot_id, zone, min_permit_tier, status, path_description, directions, floor, section) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                slots,
            )
        else:
            # Existing DB: populate nav columns for slots that have empty path_description
            connection.execute(
                """UPDATE parking_slots SET
                   path_description = 'Proceed to ' || zone,
                   directions = '[{"action":"arrive","landmark":"' || zone || '"}]'
                   WHERE path_description = '' OR path_description IS NULL"""
            )

        # ── Default admin seed ────────────────────────────────────────────────
        import hashlib
        salt = "smart-parking-salt"
        pwd = "admin123"
        hashed = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT OR IGNORE INTO admins (email, password_hash) VALUES (?, ?)",
            ("admin@campus.edu", hashed),
        )

        # ── Seed demo vehicles if table is empty ──────────────────────────────
        count = connection.execute("SELECT COUNT(*) FROM vehicle_records").fetchone()[0]
        if count == 0:
            demo_vehicles = [
                ("BR01N2323",  "Aarav Kumar",       "Student", 4),
                ("DL4CAF5765", "Dr. Priya Sharma",  "Faculty", 2),
                ("MH12DE1433", "Rajesh Patel",       "Staff",   3),
                ("KA01AB1234", "Prof. Meena Iyer",  "Faculty", 1),
                ("UP32GH5678", "Sneha Gupta",        "Student", 4),
                ("RJ14KL9012", "Amit Singh",         "Staff",   3),
                ("TN09MN3456", "Vikram Reddy",       "Student", 4),
                ("GJ05PQ7890", "Dr. Anand Joshi",   "Faculty", 2),
                ("MP09RS2345", "Pooja Verma",        "Student", 4),
                ("HR26TU6789", "Suresh Yadav",       "Staff",   3),
            ]
            connection.executemany(
                "INSERT OR IGNORE INTO vehicle_records (plate, owner_name, category, permit_tier) VALUES (?, ?, ?, ?)",
                demo_vehicles,
            )
