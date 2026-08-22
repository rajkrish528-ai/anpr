"""FastAPI application entry point. Run the venv Python with uvicorn server:app --port 8000."""
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api import router as api_router
from backend.database import initialise_database
from backend.websocket import router as websocket_router

app = FastAPI(title="Smart Parking API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(websocket_router)


def _reconcile_camera_configs() -> None:
    """
    At startup, detect all available cameras and fix any camera config that
    points to a device index which doesn't exist on this machine.

    Common case: parking was seeded with device_index=1 but the machine has
    only one built-in webcam at index 0.  This resets it to index 0 so the
    Setup page immediately shows the correct camera without manual intervention.
    """
    from backend.cameras_input import list_system_cameras, list_configs, save_config

    system_cameras = list_system_cameras()
    if not system_cameras:
        return                          # no cameras detected — nothing to fix

    available = {cam["index"] for cam in system_cameras}
    fallback = min(available)          # use the lowest-index available camera

    for cfg in list_configs():
        if cfg["device_index"] not in available:
            print(
                f"[startup] camera_configs.{cfg['role']}: "
                f"device_index={cfg['device_index']} not available -> "
                f"resetting to {fallback}"
            )
            save_config(
                role=cfg["role"],
                device_index=fallback,
                enabled=cfg["enabled"],
                detector=cfg["detector"],
                ocr_engine=cfg["ocr_engine"],
                confidence_threshold=cfg["confidence_threshold"],
            )


@app.on_event("startup")
async def on_startup():
    initialise_database()
    _reconcile_camera_configs()
    # Pre-load YOLO + Tesseract in background so camera views open instantly
    from backend.websocket import preload_analyzer
    await preload_analyzer()


@app.get("/health")
def health():
    return {"status": "ok", "service": "smart-parking-api"}
