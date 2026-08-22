"""SQLite connection and table definitions for Smart Parking."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

DATABASE_PATH = Path(__file__).resolve().parent.parent / "parking.db"

@contextmanager
def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
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
                category TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS camera_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL UNIQUE CHECK(role IN ('gate', 'parking')),
                device_index INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 0,
                detector TEXT NOT NULL DEFAULT 'yolov8_plate',
                ocr_engine TEXT NOT NULL DEFAULT 'easyocr',
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

            INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES ('campus_name', 'Smart Campus');
            INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES ('total_slots', '50');
            """
        )
