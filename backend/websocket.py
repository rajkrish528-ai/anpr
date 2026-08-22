"""WebSocket endpoints for camera previews, results, and admin live events."""
import asyncio
import base64
import time
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from . import vehicle_repository as repository
from . import cameras_input

router = APIRouter(tags=["websocket"])
clients: set[WebSocket] = set()
analyzer = None
_analyzer_lock = asyncio.Lock()

# ── Detection cooldown (prevents processing same plate every frame) ──
recent_reads: dict[str, float] = {}
COOLDOWN_SECONDS = 30


def get_analyzer():
    global analyzer
    if analyzer is None:
        from analyzer import LicensePlateAnalyzer
        analyzer = LicensePlateAnalyzer(model_path="models/best.pt", confidence=.40)
    return analyzer


async def preload_analyzer():
    """Pre-load the analyzer in a background thread so it's ready before
    any websocket client connects.  Called once from server startup."""
    global analyzer
    async with _analyzer_lock:
        if analyzer is None:
            print("[startup] Pre-loading LicensePlateAnalyzer (YOLO + Tesseract)...")
            analyzer = await asyncio.to_thread(get_analyzer)
            print("[startup] LicensePlateAnalyzer ready.")


# ─────────────────────────────────────────────────────────────
# Broadcast to all subscribed clients
# ─────────────────────────────────────────────────────────────

async def broadcast(event: dict):
    stale = []
    for client in clients:
        try:
            await client.send_json(event)
        except Exception:
            stale.append(client)
    for client in stale:
        clients.discard(client)


# ─────────────────────────────────────────────────────────────
# Core parking logic — entry / duplicate / exit
# ─────────────────────────────────────────────────────────────

async def create_result(plate: str, confidence: float, source: str, processed_image: str | None = None):
    """Process a detected plate through the full parking workflow.
    
    Returns the event dict or None if the plate is on cooldown.
    """
    plate = repository.normalise_plate(plate)
    if not plate or len(plate) < 4:
        return None

    now = time.time()

    # ── Cooldown: skip if we just processed this plate ──
    if plate in recent_reads and (now - recent_reads[plate] < COOLDOWN_SECONDS):
        recent_reads[plate] = now  # extend cooldown while vehicle lingers
        return None

    recent_reads[plate] = now

    # ── Look up vehicle info ──
    person = repository.vehicle_for_plate(plate)
    settings = repository.get_settings()
    stats = repository.get_dashboard_stats()

    # ── Check if vehicle is already parked ──
    active = repository.get_active_vehicle(plate)

    if active:
        # ALREADY PARKED — reject duplicate
        event = {
            "type": "parking_result",
            "plate": plate,
            **person,
            "slot": active["slot_id"],
            "direction": f"Already parked since {active['entry_time'][:16]}",
            "confidence": confidence,
            "source": source,
            "status": "already_parked",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "occupied": stats["occupied"],
            "totalSlots": stats["total_slots"],
            "processedImage": processed_image,
        }
        repository.add_result(event)
        await broadcast(event)
        return event

    # ── Find available slot based on permit tier ──
    permit_tier = person.get("permit_tier", 5)
    slot_info = repository.find_available_slot(permit_tier)

    if not slot_info:
        # NO SLOT AVAILABLE
        event = {
            "type": "parking_result",
            "plate": plate,
            **person,
            "slot": "N/A",
            "direction": "Parking Full",
            "confidence": confidence,
            "source": source,
            "status": "no_slot",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "occupied": stats["occupied"],
            "totalSlots": stats["total_slots"],
            "processedImage": processed_image,
        }
        repository.add_result(event)
        await broadcast(event)
        return event

    # ── Park the vehicle ──
    repository.park_vehicle(
        plate=plate,
        slot_id=slot_info["slot_id"],
        owner_name=person["studentName"],
        category=person["category"],
        permit_tier=permit_tier,
    )

    # Refresh stats after parking
    stats = repository.get_dashboard_stats()

    event = {
        "type": "parking_result",
        "plate": plate,
        **person,
        "slot": slot_info["slot_id"],
        "direction": f"{slot_info['zone']}",
        "confidence": confidence,
        "source": source,
        "status": "granted",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "occupied": stats["occupied"],
        "totalSlots": stats["total_slots"],
        "processedImage": processed_image,
    }
    repository.add_result(event)
    await broadcast(event)
    return event


async def process_exit(plate: str, source: str = "manual"):
    """Process a vehicle exit — release slot, save history, broadcast."""
    plate = repository.normalise_plate(plate)
    history = repository.exit_vehicle(plate)

    if not history:
        return None

    stats = repository.get_dashboard_stats()
    person = repository.vehicle_for_plate(plate)

    event = {
        "type": "parking_result",
        "plate": plate,
        **person,
        "slot": history["slot_id"],
        "direction": f"Departed after {history['duration_minutes']} min",
        "confidence": 1.0,
        "source": source,
        "status": "exited",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "occupied": stats["occupied"],
        "totalSlots": stats["total_slots"],
        "processedImage": None,
    }
    repository.add_result(event)
    await broadcast(event)
    return event


# ─────────────────────────────────────────────────────────────
# WebSocket handler (manual check, vehicle upsert)
# ─────────────────────────────────────────────────────────────

def analyse_image(data_url: str):
    import cv2
    import numpy as np
    encoded = data_url.split(",", 1)[-1]
    image = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image frame")
    analysis = get_analyzer().analyze(image)
    plate = next((number for number in analysis["numbers"] if number), "UNKNOWN")
    confidence = analysis["plates"][0]["confidence"] if analysis["plates"] else 0.0
    success, output = cv2.imencode(".jpg", analysis["image"])
    processed = f"data:image/jpeg;base64,{base64.b64encode(output).decode()}" if success else None
    is_stable = False
    now = time.time()
    
    if plate != "UNKNOWN":
        if plate not in temporal_buffer:
            temporal_buffer[plate] = []
        temporal_buffer[plate].append(now)
        
        temporal_buffer[plate] = [t for t in temporal_buffer[plate] if (now - t) <= STABILIZATION_WINDOW_SECONDS]
        
        if len(temporal_buffer[plate]) >= STABILIZATION_REQUIRED_READS:
            is_stable = True
            temporal_buffer[plate] = []
            
    stale_plates = [p for p, times in temporal_buffer.items() if not times or (now - times[-1]) > STABILIZATION_WINDOW_SECONDS]
    for p in stale_plates:
        del temporal_buffer[p]

    return plate, confidence, processed, is_stable


async def handle_socket(websocket: WebSocket, expected_source: str | None = None):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get("type")
            if kind == "subscribe":
                continue
            if kind == "frame":
                source = expected_source or data.get("source", "gate")
                plate, confidence, processed, is_stable = await asyncio.to_thread(analyse_image, data["image"])
                if plate != "UNKNOWN" and is_stable:
                    await create_result(plate, confidence, source, processed)
            elif kind == "manual_check":
                await create_result(repository.normalise_plate(data["plate"]), 1.0, "manual")
            elif kind == "manual_exit":
                await process_exit(repository.normalise_plate(data["plate"]), "manual")
            elif kind == "vehicle_upsert":
                plate = repository.normalise_plate(data["plate"])
                existing = repository.get_vehicle(plate)
                record = (
                    repository.update_vehicle(plate, data["studentName"], data["category"], data.get("permit_tier"))
                    if existing
                    else repository.create_vehicle(plate, data["studentName"], data["category"], data.get("permit_tier", 4))
                )
                await websocket.send_json({"type": "vehicle_saved", "record": record})
    except WebSocketDisconnect:
        pass
    except Exception as error:
        try:
            await websocket.send_json({"type": "error", "message": str(error)})
        except Exception:
            pass
    finally:
        clients.discard(websocket)


# ─────────────────────────────────────────────────────────────
# Camera frame processing & Temporal Stabilization
# ─────────────────────────────────────────────────────────────

# Buffer to track recent reads for stabilization (plate -> list of timestamps)
temporal_buffer: dict[str, list[float]] = {}
STABILIZATION_REQUIRED_READS = 2
STABILIZATION_WINDOW_SECONDS = 5.0

def _encode_frame_as_dataurl(frame):
    """Encode an OpenCV frame to a data:image/jpeg;base64,... string."""
    import cv2
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return None
    return f"data:image/jpeg;base64,{base64.b64encode(encoded).decode()}"

def process_camera_frame(frame):
    """Run full YOLO + OCR analysis on a frame. Returns (plate, confidence, processed, is_stable)."""
    analysis = get_analyzer().analyze(frame)
    plate = next((number for number in analysis["numbers"] if number), "UNKNOWN")
    confidence = analysis["plates"][0]["confidence"] if analysis["plates"] else 0.0
    processed = _encode_frame_as_dataurl(analysis["image"])
    
    is_stable = False
    now = time.time()
    
    if plate != "UNKNOWN":
        # Add to temporal buffer
        if plate not in temporal_buffer:
            temporal_buffer[plate] = []
        temporal_buffer[plate].append(now)
        
        # Clean up old entries outside the window
        temporal_buffer[plate] = [t for t in temporal_buffer[plate] if (now - t) <= STABILIZATION_WINDOW_SECONDS]
        
        # Check if we have enough reads to consider it stable
        if len(temporal_buffer[plate]) >= STABILIZATION_REQUIRED_READS:
            is_stable = True
            # Clear buffer for this plate so we don't keep firing
            temporal_buffer[plate] = []
            
    # Clean up completely stale plates from memory
    stale_plates = [p for p, times in temporal_buffer.items() if not times or (now - times[-1]) > STABILIZATION_WINDOW_SECONDS]
    for p in stale_plates:
        del temporal_buffer[p]

    return plate, confidence, processed, is_stable

# How often to run full YOLO+OCR (every Nth frame).
ANALYZE_EVERY_N_FRAMES = 5


async def configured_camera_stream(websocket: WebSocket, role: str):
    """Read configured hardware camera frames and emit processed output to its preview."""
    await websocket.accept()
    capture = None
    current_device_index = None
    frame_counter = 0

    try:
        while True:
            config = cameras_input.get_config(role)
            if not config or not config["enabled"]:
                if capture is not None:
                    await asyncio.to_thread(capture.release)
                    capture = None
                    current_device_index = None
                await websocket.send_json({
                    "type": "camera_status", "role": role, "status": "not_configured",
                    "message": f"Enable the {role} camera in Admin Setup.",
                })
                await asyncio.sleep(2.0)
                continue

            if current_device_index is not None and current_device_index != config["device_index"]:
                if capture is not None:
                    await asyncio.to_thread(capture.release)
                    capture = None

            if capture is None:
                try:
                    capture = await asyncio.to_thread(cameras_input.open_camera, config)
                    current_device_index = config["device_index"]
                    await websocket.send_json({"type": "camera_status", "role": role, "status": "streaming"})
                except Exception as e:
                    await websocket.send_json({
                        "type": "camera_status", "role": role, "status": "error", "message": str(e),
                    })
                    await asyncio.sleep(2.0)
                    continue

            consecutive_failures = 0

            for _ in range(20):
                ok, frame = await asyncio.to_thread(capture.read)
                if not ok or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures > 20:
                        raise RuntimeError("Camera stopped returning frames")
                    await asyncio.sleep(0.1)
                    continue
                consecutive_failures = 0
                frame_counter += 1

                if frame_counter % ANALYZE_EVERY_N_FRAMES == 0:
                    plate, confidence, processed, is_stable = await asyncio.to_thread(process_camera_frame, frame)
                    await websocket.send_json({
                        "type": "camera_frame", "source": role, "processedImage": processed,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    # ONLY allocate parking if the plate read is stable across multiple frames
                    if plate != "UNKNOWN" and is_stable:
                        await create_result(plate, confidence, role, processed)
                else:
                    raw = await asyncio.to_thread(_encode_frame_as_dataurl, frame)
                    await websocket.send_json({
                        "type": "camera_frame", "source": role, "processedImage": raw,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                await asyncio.sleep(0.10)
    except WebSocketDisconnect:
        pass
    except Exception as error:
        try:
            await websocket.send_json({"type": "camera_status", "role": role, "status": "error", "message": str(error)})
        except Exception:
            pass
    finally:
        if capture is not None:
            await asyncio.to_thread(capture.release)


# ─────────────────────────────────────────────────────────────
# WebSocket routes
# ─────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def live_events(websocket: WebSocket):
    await handle_socket(websocket)

@router.websocket("/ws/results")
async def results_display(websocket: WebSocket):
    await handle_socket(websocket)

@router.websocket("/ws/camera/gate")
async def gate_camera(websocket: WebSocket):
    await configured_camera_stream(websocket, "gate")

@router.websocket("/ws/camera/parking")
async def parking_camera(websocket: WebSocket):
    await configured_camera_stream(websocket, "parking")

@router.websocket("/ws/camera/preview/{device_index}")
async def raw_camera_preview(websocket: WebSocket, device_index: int):
    """Stream raw JPEG frames for the Admin Setup page preview."""
    await websocket.accept()
    try:
        await websocket.send_json({"type": "preview_status", "status": "streaming", "device_index": device_index})
        async for frame_b64 in cameras_input.raw_frame_stream(device_index, fps=10):
            await websocket.send_json({
                "type": "preview_frame",
                "device_index": device_index,
                "image": f"data:image/jpeg;base64,{frame_b64}",
            })
    except WebSocketDisconnect:
        pass
    except RuntimeError as error:
        try:
            await websocket.send_json({"type": "preview_status", "status": "error", "message": str(error)})
        except Exception:
            pass
