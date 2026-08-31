// ─────────────────────────────────────────────────────────────
// Shared domain types for the Smart Parking frontend
// ─────────────────────────────────────────────────────────────

// ── Navigation direction step ─────────────────────────────────────────────────
export interface DirectionStep {
  action: "straight" | "left" | "right" | "arrive";
  landmark: string;
}

// ── Slot navigation info ──────────────────────────────────────────────────────
export interface SlotInfo {
  slot_id: string;
  zone: string;
  min_permit_tier: number;
  status: "available" | "occupied";
  occupied_by?: string | null;
  path_description: string;
  directions: string;          // raw JSON string from DB
  directions_parsed?: DirectionStep[];
  floor: string;
  section: string;
}

// ── System log entry ──────────────────────────────────────────────────────────
export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR" | "CRITICAL";

export interface SystemLog {
  id: number;
  level: LogLevel;
  event_type: string;
  message: string;
  plate?: string | null;
  slot_id?: string | null;
  category?: string | null;
  source?: string | null;
  extra?: string | null;
  created_at: string;
}

export interface LogStats {
  total: number;
  today_debug: number;
  today_info: number;
  today_warn: number;
  today_error: number;
  today_critical: number;
}

// ── Queue entry ───────────────────────────────────────────────────────────────
export interface QueueEntry {
  id: number;
  plate: string;
  owner_name: string;
  category: string;
  permit_tier: number;
  joined_at: string;
  status: "waiting" | "assigned" | "abandoned";
}

// ── Main parking result ───────────────────────────────────────────────────────
export interface ParkingResult {
  id?: number;
  success?: boolean;
  plate_detected?: boolean;
  ocr_success?: boolean;
  plate_number: string;
  yolo_confidence?: number;
  ocr_confidence?: number;           // returned by /api/anpr/image
  ocr_engine?: string;               // returned by /api/anpr/image
  is_valid_indian_format?: boolean;  // returned by /api/anpr/image
  original_crop?: string | null;     // returned by /api/anpr/image
  preprocessed_crop?: string | null; // returned by /api/anpr/image
  studentName?: string;
  category?: string;
  slot?: string;
  direction?: string;
  path_description?: string;
  directions?: DirectionStep[];
  floor?: string;
  section?: string;
  source: string;
  status:
    | "GRANTED"
    | "ALREADY_PARKED"
    | "NO_SLOT"
    | "QUEUED"
    | "QUEUE_ASSIGNED"
    | "VERIFIED"
    | "REJECTED"
    | "EXITED"
    | "OCR_FAILED"
    | "NO_PLATE"
    | "UNKNOWN";
  queue_position?: number;
  timestamp: string;
  occupied?: number;
  totalSlots?: number;
  queue_waiting?: number;
  processedImage?: string | null;
  permit_tier?: number;
}

export interface VehicleRecord {
  id: number;
  plate: string;
  owner_name: string;
  category: string;
  permit_tier: number;
  created_at: string;
  updated_at: string;
}

export interface ActiveVehicle {
  id: number;
  plate: string;
  slot_id: string;
  owner_name: string;
  category: string;
  permit_tier: number;
  entry_time: string;
  verified: number;
}

export interface DashboardStats {
  total_slots: number;
  occupied: number;
  available: number;
  active_vehicles: number;
  today_entries: number;
  today_exits: number;
  today_rejected: number;
  queue_waiting: number;
}

export interface SystemCamera {
  index: number;
  name: string;
  available: boolean;
}

export interface CameraConfig {
  role: "gate" | "parking";
  device_index: number;
  enabled: boolean;
  detector: string;
  ocr_engine: string;
  confidence_threshold: number;
}

export interface PipelineRole {
  role: "gate" | "parking";
  device_index: number;
  enabled: boolean;
  detector: string;
  ocr_engine: string;
  confidence_threshold: number;
  camera_available: boolean;
  status: "active" | "disabled" | "unavailable";
}

export interface PipelineStatus {
  roles: PipelineRole[];
  system_cameras: SystemCamera[];
  model: string;
  db_connected: boolean;
}

export interface AppSettings {
  campus_name: string;
  total_slots: number;
}

// WebSocket message shapes
export type WsMessage =
  | { type: "camera_frame"; source: string; processedImage: string; timestamp: string }
  | { type: "parking_result" } & ParkingResult
  | { type: "camera_status"; role: string; status: string; message?: string }
  | { type: "preview_frame"; device_index: number; image: string }
  | { type: "preview_status"; status: string; message?: string; device_index?: number }
  | { type: "vehicle_saved"; record: VehicleRecord }
  | { type: "error"; message: string }
  | { type: "subscribe" };
