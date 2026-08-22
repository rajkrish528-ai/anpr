"""Pydantic request and response schemas."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["Student", "Faculty", "Staff", "Visitor"]

class VehicleCreate(BaseModel):
    plate: str = Field(min_length=2, max_length=24)
    owner_name: str = Field(min_length=2, max_length=100)
    category: Category

class VehicleUpdate(BaseModel):
    owner_name: str | None = Field(default=None, min_length=2, max_length=100)
    category: Category | None = None

class VehicleRecord(VehicleCreate):
    id: int
    created_at: datetime
    updated_at: datetime

class ManualCheck(BaseModel):
    plate: str = Field(min_length=2, max_length=24)

class ParkingResult(BaseModel):
    id: int | None = None
    plate: str
    studentName: str
    category: str
    slot: str
    direction: str
    confidence: float
    source: str
    timestamp: datetime
    processedImage: str | None = None

class CameraConfigUpdate(BaseModel):
    device_index: int = Field(ge=0, le=999)
    enabled: bool = False
    detector: Literal["yolov8_plate"] = "yolov8_plate"
    ocr_engine: Literal["easyocr"] = "easyocr"
    confidence_threshold: float = Field(default=.40, ge=.05, le=.99)

class CameraConfig(CameraConfigUpdate):
    role: Literal["gate", "parking"]

class AppSettings(BaseModel):
    campus_name: str = Field(min_length=2, max_length=100)
    total_slots: int = Field(ge=1, le=1000)
