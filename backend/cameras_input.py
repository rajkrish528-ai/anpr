"""
cameras_input.py — canonical camera discovery, configuration persistence,
snapshot capture, and raw-frame async generator for the Admin setup preview.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import AsyncIterator

from .database import get_connection


# ---------------------------------------------------------------------------
# Data-class
# ---------------------------------------------------------------------------

@dataclass
class CameraConfig:
    role: str
    device_index: int
    enabled: bool
    detector: str
    ocr_engine: str
    confidence_threshold: float


# ---------------------------------------------------------------------------
# Internal: backend-agnostic camera opener
# ---------------------------------------------------------------------------

def _open_cap(index: int):
    """
    Open a VideoCapture using the best available backend.
    """
    import cv2
    import os
    import numpy as np
    import time

    # Synthetic mock camera if physical hardware is unavailable
    if index >= 99:
        class MockCap:
            def isOpened(self): return True
            def release(self): pass
            def read(self):
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "MOCK CAMERA (No Hardware)", (50, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(frame, f"Time: {time.time():.2f}", (50, 280),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 255), 2)
                return True, frame
        return MockCap(), "mock"

    # Suppress OpenCV's verbose backend-unavailable warnings
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

    for backend_id, backend_name in [
        (cv2.CAP_DSHOW, "dshow"),
        (cv2.CAP_ANY,  "default"),
        (cv2.CAP_MSMF, "msmf"),
    ]:
        cap = cv2.VideoCapture(index, backend_id)
        if cap.isOpened():
            return cap, backend_name
        cap.release()

    raise RuntimeError(f"Camera {index} could not be opened")


# ---------------------------------------------------------------------------
# System camera discovery
# ---------------------------------------------------------------------------

def list_system_cameras(max_devices: int = 4) -> list[dict]:
    """
    Active hardware probing is disabled to prevent cv2.VideoCapture deadlocks 
    that crash the backend on Windows. We statically return Camera 0 and the Mock Camera.
    """
    return [
        {
            "index": 0,
            "name": "Hardware Camera 0",
            "available": True,
            "backend": "default",
            "readable": True,
        },
        {
            "index": 99,
            "name": "Synthetic Mock Camera",
            "available": True,
            "backend": "mock",
            "readable": True,
        }
    ]


# ---------------------------------------------------------------------------
# Persistent configuration (SQLite)
# ---------------------------------------------------------------------------

def list_configs() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT role, device_index, enabled, detector, ocr_engine, "
            "confidence_threshold FROM camera_configs ORDER BY role"
        ).fetchall()
    return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]


def get_config(role: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT role, device_index, enabled, detector, ocr_engine, "
            "confidence_threshold FROM camera_configs WHERE role = ?",
            (role,),
        ).fetchone()
    return dict(row) | {"enabled": bool(row["enabled"])} if row else None


def save_config(
    role: str,
    device_index: int,
    enabled: bool,
    detector: str,
    ocr_engine: str,
    confidence_threshold: float,
) -> dict:
    with get_connection() as conn:
        conn.execute(
            "UPDATE camera_configs "
            "SET device_index=?, enabled=?, detector=?, ocr_engine=?, "
            "    confidence_threshold=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE role=?",
            (device_index, int(enabled), detector, ocr_engine,
             confidence_threshold, role),
        )
    return get_config(role)


# ---------------------------------------------------------------------------
# Camera handle helpers (used by the YOLO streaming pipeline)
# ---------------------------------------------------------------------------

def open_camera(config: dict):
    """Open an OpenCV capture for the given config dict; raises on failure."""
    try:
        cap, _ = _open_cap(config["device_index"])
        return cap
    except RuntimeError:
        raise RuntimeError(
            f"Configured {config['role']} camera "
            f"{config['device_index']} is unavailable"
        )


def capture_snapshot(device_index: int) -> bytes:
    """Capture one JPEG frame for the Admin setup preview (HTTP endpoint)."""
    import cv2

    cap, _ = _open_cap(device_index)   # raises RuntimeError if unavailable
    try:
        # Discard first frame — some webcams return a blank/green first frame
        cap.read()
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Camera {device_index} did not return a frame")
        encoded_ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not encoded_ok:
            raise RuntimeError("Could not encode camera preview")
        return buf.tobytes()
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Raw-frame async generator  (used by /ws/camera/preview/{device_index})
# ---------------------------------------------------------------------------

async def raw_frame_stream(
    device_index: int,
    fps: int = 10,
) -> AsyncIterator[str]:
    """
    Async generator that yields base64-encoded JPEG frames at ~fps rate.
    Blocking cv2 calls run in a thread-pool executor so the event loop stays free.
    Skips None frames (webcam warm-up) instead of crashing.
    """
    import cv2

    interval = 1.0 / max(fps, 1)

    def open_cap_sync():
        cap, _ = _open_cap(device_index)
        return cap

    def read_frame(cap):
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return base64.b64encode(buf).decode()

    loop = asyncio.get_running_loop()
    cap = await loop.run_in_executor(None, open_cap_sync)

    consecutive_failures = 0
    try:
        while True:
            t_start = loop.time()
            data = await loop.run_in_executor(None, read_frame, cap)
            if data is None:
                consecutive_failures += 1
                if consecutive_failures > 20:   # ~2 s of blank frames → give up
                    raise RuntimeError(f"Camera {device_index} stopped returning frames")
                await asyncio.sleep(0.1)
                continue
            consecutive_failures = 0
            yield data
            elapsed = loop.time() - t_start
            await asyncio.sleep(max(0.0, interval - elapsed))
    finally:
        await loop.run_in_executor(None, cap.release)
