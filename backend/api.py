"""HTTP REST endpoints for admin and result-display clients."""
import asyncio
import base64
import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from . import vehicle_repository as repository
from .schemas import (
    ManualCheck, ManualExit, ParkingResult, VehicleCreate, VehicleRecord, VehicleUpdate,
    LoginRequest, AuthResponse, AppSettings, CameraConfig, CameraConfigUpdate,
    SlotInfoUpdate, ParkingVerify,
)
from . import cameras_input
from .auth import get_current_admin, verify_password, create_session_token, oauth2_scheme
from .database import get_connection
from .logger import log, LogLevel, EventType
from typing import Annotated, Any
from fastapi import Depends


router = APIRouter(prefix="/api", tags=["parking"])

# ─────────────────────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────────────────────

@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    with get_connection() as conn:
        admin = conn.execute(
            "SELECT id, password_hash FROM admins WHERE email = ?",
            (payload.email,)
        ).fetchone()

        if not admin or not verify_password(payload.password, admin["password_hash"]):
            log(LogLevel.WARN, EventType.ADMIN_ACTION,
                f"Failed login attempt for {payload.email}", source="api")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_session_token(admin["id"])
        log(LogLevel.INFO, EventType.ADMIN_ACTION,
            f"Admin login: {payload.email}", source="api")
        return {"token": token, "admin_id": admin["id"]}

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(admin: Annotated[dict, Depends(get_current_admin)], token: Annotated[str, Depends(oauth2_scheme)]):
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))

# ─────────────────────────────────────────────────────────────
# Vehicle CRUD
# ─────────────────────────────────────────────────────────────

@router.get("/vehicles", response_model=list[VehicleRecord])
def get_vehicles():
    return repository.list_vehicles()

@router.get("/vehicles/{plate}", response_model=VehicleRecord)
def get_vehicle(plate: str):
    vehicle = repository.get_vehicle(plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle record not found")
    return vehicle

@router.post("/vehicles", response_model=VehicleRecord, status_code=status.HTTP_201_CREATED)
def post_vehicle(payload: VehicleCreate, admin: Annotated[dict, Depends(get_current_admin)]):
    if repository.get_vehicle(payload.plate):
        raise HTTPException(status_code=409, detail="A vehicle with this plate already exists")
    result = repository.create_vehicle(payload.plate, payload.owner_name, payload.category, payload.permit_tier)
    log(LogLevel.INFO, EventType.ADMIN_ACTION,
        f"Vehicle added: {payload.plate} ({payload.owner_name}, {payload.category})",
        plate=payload.plate, category=payload.category, source="admin_api")
    return result

@router.patch("/vehicles/{plate}", response_model=VehicleRecord)
def patch_vehicle(plate: str, payload: VehicleUpdate, admin: Annotated[dict, Depends(get_current_admin)]):
    vehicle = repository.update_vehicle(plate, payload.owner_name, payload.category, payload.permit_tier)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle record not found")
    log(LogLevel.INFO, EventType.ADMIN_ACTION,
        f"Vehicle updated: {plate}", plate=plate, source="admin_api")
    return vehicle

@router.delete("/vehicles/{plate}", status_code=status.HTTP_204_NO_CONTENT)
def remove_vehicle(plate: str, admin: Annotated[dict, Depends(get_current_admin)]):
    if not repository.delete_vehicle(plate):
        raise HTTPException(status_code=404, detail="Vehicle record not found")
    log(LogLevel.INFO, EventType.ADMIN_ACTION,
        f"Vehicle deleted: {plate}", plate=plate, source="admin_api")

# ─────────────────────────────────────────────────────────────
# Results (live activity log)
# ─────────────────────────────────────────────────────────────

@router.get("/results", response_model=list[ParkingResult])
def get_results(limit: int = Query(default=50, ge=1, le=200)):
    return repository.list_results(limit)

@router.get("/results/latest", response_model=ParkingResult)
def get_latest_result():
    result = repository.latest_result()
    if not result:
        raise HTTPException(status_code=404, detail="No parking result exists yet")
    return result

@router.post("/results/manual", response_model=ParkingResult, status_code=status.HTTP_201_CREATED)
async def post_manual_result(payload: ManualCheck):
    from .websocket import create_result
    res = await create_result(repository.normalise_plate(payload.plate), 1.0, "manual")
    if res is None:
        raise HTTPException(status_code=400, detail="Plate is currently on cooldown.")
    return res

# ─────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard():
    """Real-time dashboard metrics computed from actual database state."""
    return repository.get_dashboard_stats()

# ─────────────────────────────────────────────────────────────
# Active Parking
# ─────────────────────────────────────────────────────────────

@router.get("/active")
def get_active_parking():
    """List all currently parked vehicles."""
    return repository.list_active_parking()

# ─────────────────────────────────────────────────────────────
# Vehicle Exit
# ─────────────────────────────────────────────────────────────

@router.post("/exit")
async def post_vehicle_exit(payload: ManualExit):
    """Manually exit a vehicle — release slot, save history, broadcast."""
    from .websocket import process_exit
    result = await process_exit(repository.normalise_plate(payload.plate), "manual")
    if result is None:
        raise HTTPException(status_code=404, detail="Vehicle is not currently parked.")
    return result

# ─────────────────────────────────────────────────────────────
# Parking Slots
# ─────────────────────────────────────────────────────────────

@router.get("/slots")
def get_slots():
    """Return all parking slots with their current status and navigation info."""
    return repository.list_slots()

@router.get("/slots/{slot_id}")
def get_slot(slot_id: str):
    """Return a single slot with full navigation info."""
    slot = repository.get_slot(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    return slot

@router.put("/slots/{slot_id}/info")
def put_slot_info(
    slot_id: str,
    payload: SlotInfoUpdate,
    admin: Annotated[dict, Depends(get_current_admin)],
):
    """Admin: set navigation details for a specific parking slot."""
    slot = repository.get_slot(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    directions_list = [step.model_dump() for step in payload.directions]
    updated = repository.update_slot_info(
        slot_id=slot_id,
        path_description=payload.path_description,
        directions=directions_list,
        floor=payload.floor,
        section=payload.section,
    )
    log(LogLevel.INFO, EventType.SLOT_INFO_UPDATED,
        f"Slot {slot_id} nav info updated by admin",
        slot_id=slot_id, source="admin_api")
    return updated

# ─────────────────────────────────────────────────────────────
# Parking Verification (parking camera confirms vehicle parked)
# ─────────────────────────────────────────────────────────────

@router.post("/parking/verify")
async def post_parking_verify(payload: ParkingVerify):
    """Manually or camera-triggered: confirm vehicle has physically parked."""
    from .websocket import verify_parking
    result = await verify_parking(
        repository.normalise_plate(payload.plate),
        source=payload.source,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Vehicle not found in active parking.")
    return result

# ─────────────────────────────────────────────────────────────
# Parking Queue
# ─────────────────────────────────────────────────────────────

@router.get("/queue")
def get_queue():
    """Return the current waiting queue."""
    return repository.queue_get_waiting()

@router.delete("/queue/{plate}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_queue(plate: str, admin: Annotated[dict, Depends(get_current_admin)]):
    """Admin: remove a vehicle from the waiting queue."""
    removed = repository.queue_remove(repository.normalise_plate(plate), status="abandoned")
    if not removed:
        raise HTTPException(status_code=404, detail="Vehicle not found in queue")
    log(LogLevel.INFO, EventType.QUEUE_ABANDONED,
        f"Vehicle {plate} removed from queue by admin",
        plate=plate, source="admin_api")

# ─────────────────────────────────────────────────────────────
# Parking History
# ─────────────────────────────────────────────────────────────

@router.get("/history")
def get_history(limit: int = Query(default=50, ge=1, le=500)):
    """Return completed parking sessions."""
    return repository.list_history(limit)

# ─────────────────────────────────────────────────────────────
# System Logs
# ─────────────────────────────────────────────────────────────

@router.get("/logs")
def get_logs(
    limit: int = Query(default=100, ge=1, le=500),
    level: str | None = Query(default=None),
    plate: str | None = Query(default=None),
):
    """Return system event logs with optional filters."""
    return repository.list_logs(limit=limit, level_filter=level, plate_filter=plate)

@router.get("/logs/stats")
def get_log_stats():
    """Return log counts per severity level for today."""
    return repository.get_log_stats()

# ─────────────────────────────────────────────────────────────
# Camera system
# ─────────────────────────────────────────────────────────────

@router.get("/cameras/system")
async def get_system_cameras():
    """Return all physically available cameras detected by OpenCV."""
    import asyncio
    return await asyncio.to_thread(cameras_input.list_system_cameras)

@router.get("/cameras/system/{device_index}/snapshot", response_class=Response)
async def get_camera_snapshot(device_index: int):
    import asyncio
    try:
        data = await asyncio.to_thread(cameras_input.capture_snapshot, device_index)
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

@router.get("/cameras", response_model=list[CameraConfig])
def get_camera_configs():
    return cameras_input.list_configs()

@router.put("/cameras/{role}", response_model=CameraConfig)
def put_camera_config(role: str, payload: CameraConfigUpdate, admin: Annotated[dict, Depends(get_current_admin)]):
    if role not in {"gate", "parking"}:
        raise HTTPException(status_code=404, detail="Camera role must be gate or parking")
    return cameras_input.save_config(role, **payload.model_dump())

# ─────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────

@router.get("/settings", response_model=AppSettings)
def get_settings():
    return repository.get_settings()

@router.put("/settings", response_model=AppSettings)
def put_settings(payload: AppSettings, admin: Annotated[dict, Depends(get_current_admin)]):
    result = repository.save_settings(payload.campus_name, payload.total_slots)
    log(LogLevel.INFO, EventType.ADMIN_ACTION,
        f"Settings updated: campus={payload.campus_name}, slots={payload.total_slots}",
        source="admin_api")
    return result

# ─────────────────────────────────────────────────────────────
# Pipeline status
# ─────────────────────────────────────────────────────────────

@router.get("/pipeline/status")
def get_pipeline_status():
    system_cameras = cameras_input.list_system_cameras()
    available_indices = {cam["index"] for cam in system_cameras}
    configs = cameras_input.list_configs()
    roles = []
    for cfg in configs:
        idx = cfg["device_index"]
        cam_available = idx in available_indices
        roles.append({
            "role": cfg["role"],
            "device_index": idx,
            "enabled": cfg["enabled"],
            "detector": cfg["detector"],
            "ocr_engine": cfg["ocr_engine"],
            "confidence_threshold": cfg["confidence_threshold"],
            "camera_available": cam_available,
            "status": (
                "active" if cfg["enabled"] and cam_available
                else "disabled" if not cfg["enabled"]
                else "unavailable"
            ),
        })
    return {
        "roles": roles,
        "system_cameras": system_cameras,
        "model": "YOLOv8 license-plate + Tesseract OCR",
        "db_connected": True,
    }


# ─────────────────────────────────────────────────────────────
# ANPR Image Test endpoint
# ─────────────────────────────────────────────────────────────

def _run_anpr_on_image(image_bytes: bytes) -> dict:
    """Synchronous ANPR worker — called via asyncio.to_thread so it
    never blocks the FastAPI event loop."""
    from backend.websocket import get_analyzer

    arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image. Make sure it is a valid JPEG, PNG, or WEBP file.")

    analysis = get_analyzer().analyze_with_crops(image)
    return analysis


@router.post("/anpr/image")
async def post_anpr_image(file: UploadFile = File(...)):
    """Accept an uploaded image, run the full ANPR pipeline, and return
    detection results including crop images — without writing to the DB
    or assigning a parking slot (read-only test endpoint).
    """
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
    content_type = (file.content_type or "").lower()
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{content_type}'. Upload a JPEG, PNG, or WEBP image.",
        )

    try:
        image_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {exc}")

    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        analysis = await asyncio.to_thread(_run_anpr_on_image, image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ANPR processing failed: {exc}")

    plate_number = analysis["best_plate_number"]
    plate_detected = len(analysis["plates"]) > 0
    ocr_success = bool(plate_number)

    db_status = "UNKNOWN"
    db_slot = None
    db_student_name = None
    db_category = None
    db_entry_time = None
    db_path_description = None
    db_directions = []
    db_floor = None
    db_section = None

    if plate_number:
        normalised = repository.normalise_plate(plate_number)
        active = repository.get_active_vehicle(normalised)
        if active:
            db_status = "ALREADY_PARKED"
            db_slot = active["slot_id"]
            db_entry_time = active["entry_time"]
            person = repository.vehicle_for_plate(normalised)
            db_student_name = person.get("studentName")
            db_category = person.get("category")
        else:
            person = repository.vehicle_for_plate(normalised)
            db_student_name = person.get("studentName")
            db_category = person.get("category")
            permit_tier = person.get("permit_tier", 5)
            slot_info = repository.find_available_slot(permit_tier)
            if slot_info:
                db_status = "GRANTED"
                db_slot = slot_info["slot_id"]
                db_path_description = slot_info.get("path_description", "")
                db_directions = slot_info.get("directions_parsed", [])
                db_floor = slot_info.get("floor", "")
                db_section = slot_info.get("section", "")
            else:
                db_status = "NO_SLOT"
    elif plate_detected:
        db_status = "OCR_FAILED"
    else:
        db_status = "NO_PLATE"

    from datetime import datetime, timezone
    return {
        "success": ocr_success,
        "plate_detected": plate_detected,
        "ocr_success": ocr_success,
        "plate_number": plate_number,
        "yolo_confidence": analysis["best_yolo_confidence"],
        "ocr_confidence": analysis["best_ocr_confidence"],
        "ocr_engine": analysis["ocr_engine"],
        "is_valid_indian_format": analysis["is_valid_indian_format"],
        "original_crop": analysis["original_crop"],
        "preprocessed_crop": analysis["preprocessed_crop"],
        "processedImage": analysis["processedImage"],
        "status": db_status,
        "slot": db_slot,
        "studentName": db_student_name,
        "category": db_category,
        "direction": db_entry_time or "",
        "path_description": db_path_description,
        "directions": db_directions,
        "floor": db_floor,
        "section": db_section,
        "source": "image_upload",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
