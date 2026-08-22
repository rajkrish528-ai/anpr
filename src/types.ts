// ─────────────────────────────────────────────────────────────
// Shared domain types for the Smart Parking frontend
// ─────────────────────────────────────────────────────────────

export interface ParkingResult {
  id?: number;
  plate: string;
  studentName: string;
  category: string;
  slot: string;
  direction: string;
  confidence: number;
  source: string;
  timestamp: string;
  occupied: number;
  totalSlots: number;
  processedImage?: string | null;
}

export interface VehicleRecord {
  id: number;
  plate: string;
  owner_name: string;
  category: string;
  created_at: string;
  updated_at: string;
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
