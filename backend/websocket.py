"""WebSocket endpoints for camera previews, results, and admin live events."""
import asyncio
import base64
import time
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from . import vehicle_repository as repository
from . import cameras_input
from .logger import log, LogLevel, EventType

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
    any websocket client connects. Called once from server startup."""
    global analyzer
    async with _analyzer_lock:
        if analyzer is None:
            log(LogLevel.INFO, EventType.SYSTEM_START, "Pre-loading LicensePlateAnalyzer (YOLO + Tesseract)...")
            analyzer = await asyncio.to_thread(get_analyzer)
            log(LogLevel.INFO, EventType.SYSTEM_START, "LicensePlateAnalyzer ready.")


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
# Core parking logic — entry / duplicate / exit / queue
# ─────────────────────────────────────────────────────────────

async def create_result(plate_number: str, yolo_confidence: float, source: str, processed_image: str | None = None):
    """Process a detected plate through the full parking workflow.

    Returns the event dict or None if the plate is on cooldown.
    """
    plate_number = repository.normalise_plate(plate_number)
    if not plate_number or len(plate_number) < 4:
        return None

    now = time.time()

    # ── Cooldown: skip if we just processed this plate ──
    if plate_number in recent_reads and (now - recent_reads[plate_number] < COOLDOWN_SECONDS):
        recent_reads[plate_number] = now  # extend cooldown while vehicle lingers
        return None

    recent_reads[plate_number] = now

    # ── Look up vehicle info ──
    person = repository.vehicle_for_plate(plate_number)
    stats = repository.get_dashboard_stats()

    log(LogLevel.INFO, EventType.PLATE_DETECTED,
        f"Plate detected: {plate_number} ({person['category']})",
        plate=plate_number, category=person["category"], source=source)

    # ── Check if vehicle is already parked ──
    active = repository.get_active_vehicle(plate_number)

    if active:
        log(LogLevel.WARN, EventType.ALREADY_PARKED,
            f"{plate_number} already parked in {active['slot_id']}",
            plate=plate_number, slot_id=active["slot_id"], source=source)
        event = {
            "success": True,
            "type": "parking_result",
            "plate_detected": True,
            "ocr_success": True,
            "plate_number": plate_number,
            "yolo_confidence": yolo_confidence,
            **person,
            "slot": active["slot_id"],
            "direction": f"Already parked since {active['entry_time'][:16]}",
            "path_description": "",
            "directions": [],
            "floor": "",
            "section": "",
            "source": source,
            "status": "ALREADY_PARKED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "occupied": stats["occupied"],
            "totalSlots": stats["total_slots"],
            "queue_waiting": stats.get("queue_waiting", 0),
            "processedImage": processed_image,
        }
        repository.add_result(event)
        await broadcast(event)
        return event

    # ── Find available slot based on permit tier ──
    permit_tier = person.get("permit_tier", 5)
    slot_info = repository.find_available_slot(permit_tier)

    if not slot_info:
        # ── NO SLOT: add to waiting queue ──
        queue_entry = repository.queue_add(
            plate_number, person["studentName"], person["category"], permit_tier
        )
        queue_pos = repository.queue_get_position(plate_number)

        log(LogLevel.WARN, EventType.NO_SLOT,
            f"Parking full — {plate_number} added to queue (position {queue_pos})",
            plate=plate_number, category=person["category"], source=source)

        event = {
            "success": True,
            "type": "parking_result",
            "plate_detected": True,
            "ocr_success": True,
            "plate_number": plate_number,
            "yolo_confidence": yolo_confidence,
            **person,
            "slot": "QUEUED",
            "direction": f"Parking full — queue position #{queue_pos}",
            "path_description": "Please wait. You will be notified when a slot is available.",
            "directions": [],
            "floor": "",
            "section": "",
            "source": source,
            "status": "QUEUED",
            "queue_position": queue_pos,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "occupied": stats["occupied"],
            "totalSlots": stats["total_slots"],
            "queue_waiting": queue_pos,
            "processedImage": processed_image,
        }
        repository.add_result(event)
        await broadcast(event)
        return event

    # ── Park the vehicle ──
    repository.park_vehicle(
        plate=plate_number,
        slot_id=slot_info["slot_id"],
        owner_name=person["studentName"],
        category=person["category"],
        permit_tier=permit_tier,
    )

    log(LogLevel.INFO, EventType.SLOT_ASSIGNED,
        f"Slot {slot_info['slot_id']} assigned to {plate_number} ({person['category']})",
        plate=plate_number, slot_id=slot_info["slot_id"], category=person["category"], source=source)

    # Refresh stats after parking
    stats = repository.get_dashboard_stats()

    directions_parsed = slot_info.get("directions_parsed", [])
    path_description = slot_info.get("path_description", f"Proceed to {slot_info['zone']}")
    floor_ = slot_info.get("floor", "")
    section_ = slot_info.get("section", "")

    # Build human-readable direction string from first step
    direction_text = slot_info["zone"]
    if directions_parsed:
        first = directions_parsed[0]
        direction_text = f"{first.get('action','Go').capitalize()} from gate → {slot_info['zone']}"

    event = {
        "success": True,
        "type": "parking_result",
        "plate_detected": True,
        "ocr_success": True,
        "plate_number": plate_number,
        "yolo_confidence": yolo_confidence,
        **person,
        "slot": slot_info["slot_id"],
        "direction": direction_text,
        "path_description": path_description,
        "directions": directions_parsed,
        "floor": floor_,
        "section": section_,
        "source": source,
        "status": "GRANTED",
        "queue_position": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "occupied": stats["occupied"],
        "totalSlots": stats["total_slots"],
        "queue_waiting": stats.get("queue_waiting", 0),
        "processedImage": processed_image,
    }
    repository.add_result(event)
    await broadcast(event)
    return event


async def process_exit(plate: str, source: str = "manual"):
    """Process a vehicle exit — release slot, save history, assign queued vehicle, broadcast."""
    plate = repository.normalise_plate(plate)
    active = repository.get_active_vehicle(plate)

    history = repository.exit_vehicle(plate)
    if not history:
        return None

    freed_slot_id = history["slot_id"]

    log(LogLevel.INFO, EventType.VEHICLE_EXITED,
        f"{plate} exited slot {freed_slot_id} after {history['duration_minutes']} min",
        plate=plate, slot_id=freed_slot_id, source=source)

    stats = repository.get_dashboard_stats()
    person = repository.vehicle_for_plate(plate)

    event = {
        "success": True,
        "type": "parking_result",
        "plate_detected": True,
        "ocr_success": True,
        "plate_number": plate,
        "yolo_confidence": 1.0,
        **person,
        "slot": freed_slot_id,
        "direction": f"Departed after {history['duration_minutes']} min",
        "path_description": "",
        "directions": [],
        "floor": "",
        "section": "",
        "source": source,
        "status": "EXITED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "occupied": stats["occupied"],
        "totalSlots": stats["total_slots"],
        "queue_waiting": stats.get("queue_waiting", 0),
        "processedImage": None,
    }
    repository.add_result(event)
    await broadcast(event)

    # ── Auto-assign next queued vehicle if one exists ──
    await _try_assign_queued(freed_slot_id)

    return event


async def _try_assign_queued(freed_slot_id: str):
    """Check queue and assign the next eligible vehicle to the newly freed slot."""
    assigned = await asyncio.to_thread(repository.queue_assign_next, freed_slot_id)
    if not assigned:
        return

    slot_info = assigned["slot_info"]
    directions_parsed = slot_info.get("directions_parsed", [])
    path_description = slot_info.get("path_description", f"Proceed to {slot_info['zone']}")

    log(LogLevel.INFO, EventType.QUEUE_ASSIGNED,
        f"Queue vehicle {assigned['plate']} auto-assigned to {slot_info['slot_id']}",
        plate=assigned["plate"], slot_id=slot_info["slot_id"], category=assigned["category"])

    stats = repository.get_dashboard_stats()

    direction_text = slot_info["zone"]
    if directions_parsed:
        first = directions_parsed[0]
        direction_text = f"{first.get('action','Go').capitalize()} from gate → {slot_info['zone']}"

    queue_event = {
        "success": True,
        "type": "parking_result",
        "plate_detected": True,
        "ocr_success": True,
        "plate_number": assigned["plate"],
        "yolo_confidence": 1.0,
        "studentName": assigned["owner_name"],
        "category": assigned["category"],
        "permit_tier": assigned["permit_tier"],
        "slot": slot_info["slot_id"],
        "direction": direction_text,
        "path_description": path_description,
        "directions": directions_parsed,
        "floor": slot_info.get("floor", ""),
        "section": slot_info.get("section", ""),
        "source": "queue_auto",
        "status": "QUEUE_ASSIGNED",
        "queue_position": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "occupied": stats["occupied"],
        "totalSlots": stats["total_slots"],
        "queue_waiting": stats.get("queue_waiting", 0),
        "processedImage": None,
    }
    repository.add_result(queue_event)
    await broadcast(queue_event)


async def verify_parking(plate: str, source: str = "parking_camera") -> dict | None:
    """Confirm that a vehicle has physically parked in its assigned slot.

    Called when the parking camera detects a plate that matches an active_parking record.
    """
    plate = repository.normalise_plate(plate)
    active = repository.get_active_vehicle(plate)
    if not active:
        return None  # vehicle not assigned — ignore

    success = await asyncio.to_thread(repository.verify_vehicle_parked, plate)
    if not success:
        return None

    log(LogLevel.INFO, EventType.SLOT_VERIFIED,
        f"Vehicle {plate} physically verified in slot {active['slot_id']}",
        plate=plate, slot_id=active["slot_id"], source=source)

    stats = repository.get_dashboard_stats()
    person = repository.vehicle_for_plate(plate)

    event = {
        "success": True,
        "type": "parking_result",
        "plate_detected": True,
        "ocr_success": True,
        "plate_number": plate,
        "yolo_confidence": 1.0,
        **person,
        "slot": active["slot_id"],
        "direction": f"Verified parked in {active['slot_id']}",
        "path_description": "",
        "directions": [],
        "floor": "",
        "section": "",
        "source": source,
        "status": "VERIFIED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "occupied": stats["occupied"],
        "totalSlots": stats["total_slots"],
        "queue_waiting": stats.get("queue_waiting", 0),
        "processedImage": None,
    }
    await broadcast(event)
    return event


# ─────────────────────────────────────────────────────────────
# WebSocket handler (manual check, vehicle upsert, verify)
# ─────────────────────────────────────────────────────────────

def analyse_image(data_url: str):
    import cv2
    import numpy as np
    encoded = data_url.split(",", 1)[-1]
    image = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image frame")
    analysis = get_analyzer().analyze(image)
    plate_detected = len(analysis["plates"]) > 0
    yolo_confidence = analysis["plates"][0]["confidence"] if plate_detected else 0.0
    plate_number = next((number for number in analysis["numbers"] if number), "")
    ocr_success = bool(plate_number)

    success, output = cv2.imencode(".jpg", analysis["image"])
    processed = f"data:image/jpeg;base64,{base64.b64encode(output).decode()}" if success else None
    is_stable = False
    now = time.time()

    if plate_number:
        if plate_number not in temporal_buffer:
            temporal_buffer[plate_number] = []
        temporal_buffer[plate_number].append(now)

        temporal_buffer[plate_number] = [t for t in temporal_buffer[plate_number] if (now - t) <= STABILIZATION_WINDOW_SECONDS]

        if len(temporal_buffer[plate_number]) >= STABILIZATION_REQUIRED_READS:
            is_stable = True
            temporal_buffer[plate_number] = []

    stale_plates = [p for p, times in temporal_buffer.items() if not times or (now - times[-1]) > STABILIZATION_WINDOW_SECONDS]
    for p in stale_plates:
        del temporal_buffer[p]

    return plate_detected, plate_number, yolo_confidence, ocr_success, processed, is_stable


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
                plate_detected, plate_number, yolo_confidence, ocr_success, processed, is_stable = await asyncio.to_thread(analyse_image, data["image"])

                if plate_detected and not ocr_success:
                    log(LogLevel.WARN, EventType.PLATE_OCR_FAILED,
                        "Plate detected but OCR failed", source=source)
                    await broadcast({
                        "success": False,
                        "type": "parking_result",
                        "plate_detected": True,
                        "ocr_success": False,
                        "plate_number": "",
                        "yolo_confidence": yolo_confidence,
                        "source": source,
                        "status": "OCR_FAILED",
                        "processedImage": processed,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                elif plate_detected and ocr_success and is_stable:
                    await create_result(plate_number, yolo_confidence, source, processed)
            elif kind == "manual_check":
                await create_result(repository.normalise_plate(data["plate"]), 1.0, "manual")
            elif kind == "manual_exit":
                await process_exit(repository.normalise_plate(data["plate"]), "manual")
            elif kind == "parking_verify":
                # Parking camera reports a vehicle physically confirmed
                plate = repository.normalise_plate(data.get("plate", ""))
                if plate:
                    await verify_parking(plate, source="parking_camera")
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
    """Run full YOLO + OCR analysis on a frame. Returns (plate, confidence, processed, is_stable).

    Uses fast=True OCR (2 variants, 1 PSM) for low latency. The uploaded-image
    endpoint uses the full 5-variant / 3-PSM path for maximum accuracy.
    """
    analysis = get_analyzer().analyze(frame, fast=True)
    plate_detected = len(analysis["plates"]) > 0
    yolo_confidence = analysis["plates"][0]["confidence"] if plate_detected else 0.0
    plate_number = next((number for number in analysis["numbers"] if number), "")
    ocr_success = bool(plate_number)
    processed = _encode_frame_as_dataurl(analysis["image"])

    is_stable = False
    now = time.time()

    if plate_number:
        if plate_number not in temporal_buffer:
            temporal_buffer[plate_number] = []
        temporal_buffer[plate_number].append(now)

        temporal_buffer[plate_number] = [t for t in temporal_buffer[plate_number] if (now - t) <= STABILIZATION_WINDOW_SECONDS]

        if len(temporal_buffer[plate_number]) >= STABILIZATION_REQUIRED_READS:
            is_stable = True
            temporal_buffer[plate_number] = []

    stale_plates = [p for p, times in temporal_buffer.items() if not times or (now - times[-1]) > STABILIZATION_WINDOW_SECONDS]
    for p in stale_plates:
        del temporal_buffer[p]

    return plate_detected, plate_number, yolo_confidence, ocr_success, processed, is_stable


# How often to run full YOLO+OCR (every Nth frame).
ANALYZE_EVERY_N_FRAMES = 5


async def configured_camera_stream(websocket: WebSocket, role: str):
    """Read configured hardware camera frames and emit processed output to its preview.

    Architecture: frame delivery and ANPR inference are decoupled.
    - Raw/processed frames are streamed continuously at ~10 fps so the video is smooth.
    - ANPR inference (YOLO+OCR) runs as a background task every Nth frame.
    - If an inference is already running we skip starting a new one (no pile-up).
    - For the 'parking' role: if detected plate matches an active_parking entry,
      trigger verify_parking() to confirm the vehicle has physically parked.
    """
    await websocket.accept()
    capture = None
    current_device_index = None
    frame_counter = 0
    inference_running = False

    async def run_inference_and_broadcast(frame, src: str):
        """Fire-and-forget coroutine: runs ANPR and broadcasts; called via create_task."""
        nonlocal inference_running
        try:
            plate_detected, plate_number, yolo_confidence, ocr_success, processed, is_stable = \
                await asyncio.to_thread(process_camera_frame, frame)

            try:
                await websocket.send_json({
                    "type": "camera_frame", "source": src, "processedImage": processed,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass

            if plate_detected and not ocr_success:
                now = time.time()
                if now - recent_reads.get("_OCR_FAILED_", 0) > COOLDOWN_SECONDS:
                    recent_reads["_OCR_FAILED_"] = now
                    log(LogLevel.WARN, EventType.PLATE_OCR_FAILED,
                        f"[{src}] Plate detected, OCR failed", source=src)
                    event = {
                        "success": False,
                        "type": "parking_result",
                        "plate_detected": True,
                        "ocr_success": False,
                        "plate_number": "",
                        "yolo_confidence": yolo_confidence,
                        "source": src,
                        "status": "OCR_FAILED",
                        "processedImage": processed,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    repository.add_result(event)
                    await broadcast(event)
            elif plate_detected and ocr_success and is_stable:
                if src == "parking":
                    # Parking camera: check if vehicle is already assigned → verify
                    active = repository.get_active_vehicle(plate_number)
                    if active:
                        await verify_parking(plate_number, source="parking_camera")
                    # else: might be a new entry via the parking camera (edge case)
                else:
                    await create_result(plate_number, yolo_confidence, src, processed)
        except Exception as err:
            log(LogLevel.ERROR, EventType.CAMERA_ERROR, f"Inference task error [{role}]: {err}", source=role)
        finally:
            inference_running = False

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
                    log(LogLevel.INFO, EventType.SYSTEM_START, f"Camera [{role}] streaming started", source=role)
                    await websocket.send_json({"type": "camera_status", "role": role, "status": "streaming"})
                except Exception as e:
                    log(LogLevel.ERROR, EventType.CAMERA_ERROR, f"Camera [{role}] failed to open: {e}", source=role)
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

                if frame_counter % ANALYZE_EVERY_N_FRAMES == 0 and not inference_running:
                    inference_running = True
                    asyncio.create_task(run_inference_and_broadcast(frame.copy(), role))
                else:
                    raw = await asyncio.to_thread(_encode_frame_as_dataurl, frame)
                    try:
                        await websocket.send_json({
                            "type": "camera_frame", "source": role, "processedImage": raw,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception:
                        break

                await asyncio.sleep(0.05)  # ~20 fps cap for smooth video
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
