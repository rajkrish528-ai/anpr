"""HTTP REST endpoints for admin and result-display clients."""
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from . import vehicle_repository as repository
from .schemas import (
    ManualCheck, ManualExit, ParkingResult, VehicleCreate, VehicleRecord, VehicleUpdate,
    LoginRequest, AuthResponse, AppSettings, CameraConfig, CameraConfigUpdate,
)
from . import cameras_input
from .auth import get_current_admin, verify_password, create_session_token, oauth2_scheme
from .database import get_connection
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_session_token(admin["id"])
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
    return repository.create_vehicle(payload.plate, payload.owner_name, payload.category, payload.permit_tier)

@router.patch("/vehicles/{plate}", response_model=VehicleRecord)
def patch_vehicle(plate: str, payload: VehicleUpdate, admin: Annotated[dict, Depends(get_current_admin)]):
    vehicle = repository.update_vehicle(plate, payload.owner_name, payload.category, payload.permit_tier)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle record not found")
    return vehicle

@router.delete("/vehicles/{plate}", status_code=status.HTTP_204_NO_CONTENT)
def remove_vehicle(plate: str, admin: Annotated[dict, Depends(get_current_admin)]):
    if not repository.delete_vehicle(plate):
        raise HTTPException(status_code=404, detail="Vehicle record not found")

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
    """Return all parking slots with their current status."""
    return repository.list_slots()

# ─────────────────────────────────────────────────────────────
# Parking History
# ─────────────────────────────────────────────────────────────

@router.get("/history")
def get_history(limit: int = Query(default=50, ge=1, le=500)):
    """Return completed parking sessions."""
    return repository.list_history(limit)

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
    return repository.save_settings(payload.campus_name, payload.total_slots)

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
