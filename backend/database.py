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

def initialise_database():
    """Create persistent vehicle and result tables if they do not exist."""
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
                occupied_by TEXT DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS active_parking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL UNIQUE,
                slot_id TEXT NOT NULL,
                owner_name TEXT NOT NULL DEFAULT 'Unknown',
                category TEXT NOT NULL DEFAULT 'Visitor',
                permit_tier INTEGER NOT NULL DEFAULT 4,
                entry_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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

            INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES ('campus_name', 'Smart Campus');
            INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES ('total_slots', '50');
            """
        )

        # ── Add permit_tier column if migrating from old schema ──
        try:
            connection.execute("SELECT permit_tier FROM vehicle_records LIMIT 1")
        except sqlite3.OperationalError:
            connection.execute("ALTER TABLE vehicle_records ADD COLUMN permit_tier INTEGER NOT NULL DEFAULT 4")

        # ── Add status column to parking_results if migrating ──
        try:
            connection.execute("SELECT status FROM parking_results LIMIT 1")
        except sqlite3.OperationalError:
            connection.execute("ALTER TABLE parking_results ADD COLUMN status TEXT NOT NULL DEFAULT 'granted'")

        # ── Seed parking slots (S1–S50) ──
        existing = connection.execute("SELECT COUNT(*) FROM parking_slots").fetchone()[0]
        if existing == 0:
            slots = []
            for i in range(1, 51):
                if i <= 5:
                    # Tier 1 — VIP / Director
                    zone, tier = "VIP Wing", 1
                elif i <= 15:
                    # Tier 2 — Faculty
                    zone, tier = "Faculty Block A", 2
                elif i <= 25:
                    # Tier 3 — Staff
                    zone, tier = "Staff Block B", 3
                elif i <= 45:
                    # Tier 4 — Student
                    zone, tier = "Student Lot C", 4
                else:
                    # Tier 5 — Visitor
                    zone, tier = "Visitor Lot D", 5
                slots.append((f"S{i}", zone, tier, "available"))
            connection.executemany(
                "INSERT INTO parking_slots (slot_id, zone, min_permit_tier, status) VALUES (?, ?, ?, ?)",
                slots,
            )

        # ── Default admin seed: admin@campus.edu / admin123 ──
        import hashlib
        salt = "smart-parking-salt"
        pwd = "admin123"
        hashed = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()

        connection.execute(
            "INSERT OR IGNORE INTO admins (email, password_hash) VALUES (?, ?)",
            ("admin@campus.edu", hashed)
        )

        # ── Seed demo vehicles if table is empty ──
        count = connection.execute("SELECT COUNT(*) FROM vehicle_records").fetchone()[0]
        if count == 0:
            demo_vehicles = [
                ("BR01N2323", "Aarav Kumar", "Student", 4),
                ("DL4CAF5765", "Dr. Priya Sharma", "Faculty", 2),
                ("MH12DE1433", "Rajesh Patel", "Staff", 3),
                ("KA01AB1234", "Prof. Meena Iyer", "Faculty", 1),
                ("UP32GH5678", "Sneha Gupta", "Student", 4),
                ("RJ14KL9012", "Amit Singh", "Staff", 3),
                ("TN09MN3456", "Vikram Reddy", "Student", 4),
                ("GJ05PQ7890", "Dr. Anand Joshi", "Faculty", 2),
                ("MP09RS2345", "Pooja Verma", "Student", 4),
                ("HR26TU6789", "Suresh Yadav", "Staff", 3),
            ]
            connection.executemany(
                "INSERT OR IGNORE INTO vehicle_records (plate, owner_name, category, permit_tier) VALUES (?, ?, ?, ?)",
                demo_vehicles,
            )
