"""WebSocket endpoints for camera previews, results, and admin live events."""
import asyncio
import base64
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from . import vehicle_repository as repository
from . import cameras_input

router = APIRouter(tags=["websocket"])
clients: set[WebSocket] = set()
occupied = 27
slots = ["S2", "S3", "S5", "S7", "S8"]
analyzer = None

def get_analyzer():
    global analyzer
    if analyzer is None:
        from analyzer import LicensePlateAnalyzer
        analyzer = LicensePlateAnalyzer(model_path="models/best.pt", confidence=.40, use_gpu=False)
    return analyzer

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
    return plate, confidence, processed

async def broadcast(event: dict):
    stale = []
    for client in clients:
        try:
            await client.send_json(event)
        except Exception:
            stale.append(client)
    for client in stale:
        clients.discard(client)

async def create_result(plate: str, confidence: float, source: str, processed_image: str | None = None):
    global occupied
    settings = repository.get_settings()
    person = repository.vehicle_for_plate(plate)
    slot = slots[occupied % len(slots)]
    occupied = min(occupied + 1, settings["total_slots"])
    event = {"type": "parking_result", "plate": plate, **person, "slot": slot, "direction": "Level 1 · East Wing", "confidence": confidence, "source": source, "timestamp": datetime.now(timezone.utc).isoformat(), "occupied": occupied, "totalSlots": settings["total_slots"], "processedImage": processed_image}
    repository.add_result(event)
    await broadcast(event)
    return event

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
                plate, confidence, processed = await asyncio.to_thread(analyse_image, data["image"])
                await create_result(plate, confidence, source, processed)
            elif kind == "manual_check":
                await create_result(repository.normalise_plate(data["plate"]), 1.0, "manual")
            elif kind == "vehicle_upsert":
                plate = repository.normalise_plate(data["plate"])
                existing = repository.get_vehicle(plate)
                record = repository.update_vehicle(plate, data["studentName"], data["category"]) if existing else repository.create_vehicle(plate, data["studentName"], data["category"])
                await websocket.send_json({"type": "vehicle_saved", "record": record})
    except WebSocketDisconnect:
        pass
    except Exception as error:
        await websocket.send_json({"type": "error", "message": str(error)})
    finally:
        clients.discard(websocket)

def process_camera_frame(frame):
    import cv2
    analysis = get_analyzer().analyze(frame)
    plate = next((number for number in analysis["numbers"] if number), "UNKNOWN")
    confidence = analysis["plates"][0]["confidence"] if analysis["plates"] else 0.0
    ok, encoded = cv2.imencode(".jpg", analysis["image"])
    output = f"data:image/jpeg;base64,{base64.b64encode(encoded).decode()}" if ok else None
    return plate, confidence, output

async def configured_camera_stream(websocket: WebSocket, role: str):
    """Read configured hardware camera frames and emit processed output to its preview."""
    await websocket.accept()
    config = cameras_input.get_config(role)
    if not config or not config["enabled"]:
        await websocket.send_json({"type": "camera_status", "role": role, "status": "not_configured", "message": f"Enable the {role} camera in Admin Setup."})
        await websocket.close()
        return
    capture = None
    last_plate, last_result_at = "", 0.0
    consecutive_failures = 0
    try:
        capture = await asyncio.to_thread(cameras_input.open_camera, config)
        await websocket.send_json({"type": "camera_status", "role": role, "status": "streaming"})
        while True:
            ok, frame = await asyncio.to_thread(capture.read)
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures > 20:
                    raise RuntimeError("Camera stopped returning frames")
                await asyncio.sleep(0.1)
                continue
            consecutive_failures = 0
            plate, confidence, processed = await asyncio.to_thread(process_camera_frame, frame)
            await websocket.send_json({"type": "camera_frame", "source": role, "processedImage": processed, "timestamp": datetime.now(timezone.utc).isoformat()})
            now = asyncio.get_running_loop().time()
            if plate != "UNKNOWN" and (plate != last_plate or now - last_result_at > 12):
                await create_result(plate, confidence, role, processed)
                last_plate, last_result_at = plate, now
            await asyncio.sleep(.25)
    except WebSocketDisconnect:
        pass
    except Exception as error:
        try:
            await websocket.send_json({"type": "camera_status", "role": role, "status": "error", "message": str(error)})
        except Exception:
            pass
    finally:
        if capture is not None:
            capture.release()

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
    """
    Stream raw (un-processed) JPEG frames from the given device index.
    Used by the Admin Setup page to show live preview of each physical
    camera before the user commits to a configuration.
    """
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
