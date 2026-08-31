"""Pydantic request and response schemas."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

Category = Literal["Student", "Faculty", "Staff", "Visitor"]
PermitTier = Literal[1, 2, 3, 4, 5]

class VehicleCreate(BaseModel):
    plate: str = Field(min_length=2, max_length=24)
    owner_name: str = Field(min_length=2, max_length=100)
    category: Category
    permit_tier: PermitTier = 4

class VehicleUpdate(BaseModel):
    owner_name: str | None = Field(default=None, min_length=2, max_length=100)
    category: Category | None = None
    permit_tier: PermitTier | None = None

class VehicleRecord(VehicleCreate):
    id: int
    created_at: datetime
    updated_at: datetime

class ManualCheck(BaseModel):
    plate: str = Field(min_length=2, max_length=24)

class ManualExit(BaseModel):
    plate: str = Field(min_length=2, max_length=24)

class ParkingResult(BaseModel):
    id: int | None = None
    success: bool | None = None
    plate_detected: bool | None = None
    ocr_success: bool | None = None
    plate_number: str | None = None
    yolo_confidence: float | None = None
    plate: str | None = None
    studentName: str | None = None
    category: str | None = None
    slot: str | None = None
    direction: str | None = None
    path_description: str | None = None
    directions: list[dict] | None = None
    floor: str | None = None
    section: str | None = None
    source: str | None = None
    status: str = "GRANTED"
    queue_position: int | None = None
    timestamp: datetime
    processedImage: str | None = None
    occupied: int | None = None
    totalSlots: int | None = None
    queue_waiting: int | None = None

class CameraConfigUpdate(BaseModel):
    device_index: int = Field(ge=0, le=999)
    enabled: bool = False
    detector: Literal["yolov8_plate"] = "yolov8_plate"
    ocr_engine: Literal["tesseract"] = "tesseract"
    confidence_threshold: float = Field(default=.40, ge=.05, le=.99)

class CameraConfig(CameraConfigUpdate):
    role: Literal["gate", "parking"]

class AppSettings(BaseModel):
    campus_name: str = Field(min_length=2, max_length=100)
    total_slots: int = Field(ge=1, le=1000)

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    token: str
    admin_id: int

# ── Direction step in slot navigation ─────────────────────────────────────────
class DirectionStep(BaseModel):
    action: Literal["straight", "left", "right", "arrive"]
    landmark: str

# ── Slot navigation info update (admin) ──────────────────────────────────────
class SlotInfoUpdate(BaseModel):
    path_description: str = Field(default="", max_length=500)
    directions: list[DirectionStep] = Field(default_factory=list)
    floor: str = Field(default="Ground", max_length=50)
    section: str = Field(default="Main", max_length=50)

# ── System log entry ──────────────────────────────────────────────────────────
class SystemLog(BaseModel):
    id: int
    level: str
    event_type: str
    message: str
    plate: str | None = None
    slot_id: str | None = None
    category: str | None = None
    source: str | None = None
    extra: str | None = None
    created_at: datetime

# ── Queue entry ───────────────────────────────────────────────────────────────
class QueueEntry(BaseModel):
    id: int
    plate: str
    owner_name: str
    category: str
    permit_tier: int
    joined_at: datetime
    status: str

# ── Parking verify ────────────────────────────────────────────────────────────
class ParkingVerify(BaseModel):
    plate: str = Field(min_length=2, max_length=24)
    source: str = "manual"
