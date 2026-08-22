// ─────────────────────────────────────────────────────────────
// SystemSetup page — full camera & pipeline configuration
// ─────────────────────────────────────────────────────────────
import React, { useCallback, useEffect, useState } from "react";
import { Header } from "../Layout";
import { SetupCameraPreview } from "../components/SetupCameraPreview";
import { api } from "../api";
import type {
  CameraConfig,
  PipelineStatus,
  SystemCamera,
} from "../types";

// ── Pipeline status bar ───────────────────────────────────────
function PipelineBar({ status }: { status: PipelineStatus | null }) {
  if (!status) {
    return (
      <div className="pipeline-bar loading">
        <span className="pipe-spinner">⟳</span> Loading pipeline status…
      </div>
    );
  }
  return (
    <div className="pipeline-bar">
      <div className="pipe-item">
        <span className="pipe-icon">◎</span>
        <div>
          <b>Database</b>
          <small className={status.db_connected ? "ok" : "err"}>
            {status.db_connected ? "Connected" : "Disconnected"}
          </small>
        </div>
      </div>

      <div className="pipe-sep" />

      <div className="pipe-item">
        <span className="pipe-icon">⬡</span>
        <div>
          <b>YOLO model</b>
          <small className="ok">{status.model}</small>
        </div>
      </div>

      {status.roles.map((r) => (
        <React.Fragment key={r.role}>
          <div className="pipe-sep" />
          <div className="pipe-item">
            <span className="pipe-icon">{r.role === "gate" ? "◉" : "▧"}</span>
            <div>
              <b>{r.role === "gate" ? "Gate" : "Parking"} cam</b>
              <small
                className={
                  r.status === "active"
                    ? "ok"
                    : r.status === "disabled"
                    ? "warn"
                    : "err"
                }
              >
                {r.status === "active"
                  ? "Active"
                  : r.status === "disabled"
                  ? "Disabled"
                  : "Unavailable"}{" "}
                {r.camera_available
                  ? `· cam ${r.device_index}`
                  : "· no device"}
              </small>
            </div>
          </div>
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Camera config card ────────────────────────────────────────
interface CardProps {
  config: CameraConfig;
  cameras: SystemCamera[];
  onChange: (key: keyof CameraConfig, value: CameraConfig[keyof CameraConfig]) => void;
  onSave: () => void;
  saving: boolean;
}

function CameraConfigCard({ config, cameras, onChange, onSave, saving }: CardProps) {
  const isGate = config.role === "gate";
  return (
    <article className="setup-card">
      <div className="setup-card-header">
        <span className="setup-card-icon">{isGate ? "◉" : "▧"}</span>
        <div>
          <h3>{isGate ? "Gate camera" : "Parking camera"}</h3>
          <small>{isGate ? "Entry / exit point" : "Parking bay monitoring"}</small>
        </div>
        <label className="toggle-wrap">
          <input
            type="checkbox"
            checked={config.enabled}
            disabled={cameras.length === 0}
            onChange={(e) => onChange("enabled", e.target.checked)}
          />
          <span className="toggle-track">
            <span className="toggle-thumb" />
          </span>
          <span>{config.enabled ? "Enabled" : "Disabled"}</span>
        </label>
      </div>

      {/* Live preview — reconnects instantly when dropdown changes */}
      <SetupCameraPreview
        deviceIndex={cameras.length > 0 ? config.device_index : -1}
        label={isGate ? "GATE CAM" : "PARKING CAM"}
      />

      <div className="setup-fields">
        <label className="setup-label">
          <span>System camera</span>
          <select
            value={config.device_index}
            disabled={cameras.length === 0}
            onChange={(e) => onChange("device_index", +e.target.value)}
          >
            {cameras.length > 0 ? (
              cameras.map((cam) => (
                <option key={cam.index} value={cam.index}>
                  {cam.name}
                  {cam.available ? "" : " (unavailable)"}
                </option>
              ))
            ) : (
              <option value={-1}>No camera detected</option>
            )}
          </select>
        </label>

        <label className="setup-label">
          <span>Plate detector</span>
          <select
            value={config.detector}
            onChange={(e) => onChange("detector", e.target.value)}
          >
            <option value="yolov8_plate">YOLOv8 license plate</option>
          </select>
        </label>

        <label className="setup-label">
          <span>OCR engine</span>
          <select
            value={config.ocr_engine}
            onChange={(e) => onChange("ocr_engine", e.target.value)}
          >
            <option value="easyocr">EasyOCR</option>
          </select>
        </label>

        <label className="setup-label">
          <span>
            Detection confidence —{" "}
            <b>{Math.round(config.confidence_threshold * 100)}%</b>
          </span>
          <input
            type="range"
            min="0.05"
            max="0.99"
            step="0.05"
            value={config.confidence_threshold}
            onChange={(e) =>
              onChange("confidence_threshold", parseFloat(e.target.value))
            }
          />
          <div className="conf-scale">
            <span>Low</span>
            <span>High</span>
          </div>
        </label>
      </div>

      <button
        className="primary setup-save-btn"
        disabled={cameras.length === 0 || saving}
        type="button"
        onClick={onSave}
      >
        {saving
          ? "Saving…"
          : `Save ${isGate ? "gate" : "parking"} setup`}
      </button>
    </article>
  );
}

// ── Flow info strip ───────────────────────────────────────────
function FlowInfo() {
  const steps = [
    { n: "1", title: "Select camera", desc: "Choose which physical camera covers each zone" },
    { n: "2", title: "Save config", desc: "Config stored in SQLite; preview updates instantly" },
    { n: "3", title: "Enable", desc: "Toggle the camera on to start the YOLO pipeline" },
    { n: "4", title: "Live result", desc: "Plates detected → DB lookup → slot assignment → display" },
  ];
  return (
    <div className="setup-flow-info">
      {steps.map((s, i) => (
        <React.Fragment key={s.n}>
          <div className="flow-step">
            <span>{s.n}</span>
            <b>{s.title}</b>
            <small>{s.desc}</small>
          </div>
          {i < steps.length - 1 && <div className="flow-arrow">→</div>}
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Notice banner ─────────────────────────────────────────────
interface Notice {
  text: string;
  type: "ok" | "err" | "info";
}

// ── Main page ─────────────────────────────────────────────────
export function SystemSetup() {
  const [cameras, setCameras] = useState<SystemCamera[]>([]);
  const [configs, setConfigs] = useState<CameraConfig[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [notice, setNotice] = useState<Notice>({ text: "", type: "info" });
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [loadState, setLoadState] = useState("Loading…");

  const load = useCallback(async () => {
    setLoadState("Detecting cameras…");
    try {
      const [systemCams, savedCfgs, pipeline] = await Promise.all([
        api<SystemCamera[]>("/cameras/system"),
        api<CameraConfig[]>("/cameras"),
        api<PipelineStatus>("/pipeline/status"),
      ]);

      setCameras(systemCams);
      setPipelineStatus(pipeline);

      // Reconcile saved config device_index with what's physically present
      const reconciled = savedCfgs.map((cfg) => {
        const exists = systemCams.some((c) => c.index === cfg.device_index);
        return exists ? cfg : { ...cfg, device_index: systemCams[0]?.index ?? 0 };
      });
      setConfigs(reconciled);

      setLoadState(
        systemCams.length > 0
          ? `${systemCams.length} camera${systemCams.length > 1 ? "s" : ""} detected.`
          : "No cameras detected. Connect a USB camera and refresh.",
      );
    } catch {
      setLoadState("Cannot reach the backend. Is the server running?");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const updateConfig = (
    role: CameraConfig["role"],
    key: keyof CameraConfig,
    value: CameraConfig[keyof CameraConfig],
  ) =>
    setConfigs((prev) =>
      prev.map((c) => (c.role === role ? { ...c, [key]: value } : c)),
    );

  const saveConfig = async (config: CameraConfig) => {
    setSaving((s) => ({ ...s, [config.role]: true }));
    try {
      await api(`/cameras/${config.role}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_index: config.device_index,
          enabled: config.enabled,
          detector: config.detector,
          ocr_engine: config.ocr_engine,
          confidence_threshold: config.confidence_threshold,
        }),
      });
      setNotice({
        text: `✓ ${config.role === "gate" ? "Gate" : "Parking"} camera saved.`,
        type: "ok",
      });
      api<PipelineStatus>("/pipeline/status").then(setPipelineStatus).catch(() => {});
    } catch (err) {
      setNotice({ text: `Error: ${(err as Error).message}`, type: "err" });
    } finally {
      setSaving((s) => ({ ...s, [config.role]: false }));
    }
  };

  return (
    <>
      <Header
        title="System setup"
        note="Configure cameras, recognition pipeline, and detection parameters."
      />

      <PipelineBar status={pipelineStatus} />

      <div className="setup-toolbar">
        <p className="setup-state-msg">{loadState}</p>
        <button type="button" onClick={load}>
          ↺ Refresh cameras
        </button>
      </div>

      {notice.text && (
        <div
          className={`setup-notice ${notice.type}`}
          onClick={() => setNotice({ text: "", type: "info" })}
        >
          {notice.text}{" "}
          <span className="notice-dismiss">✕</span>
        </div>
      )}

      <div className="setup-grid">
        {configs.map((cfg) => (
          <CameraConfigCard
            key={cfg.role}
            config={cfg}
            cameras={cameras}
            onChange={(key, val) => updateConfig(cfg.role, key, val)}
            onSave={() => saveConfig(cfg)}
            saving={saving[cfg.role] ?? false}
          />
        ))}
      </div>

      <FlowInfo />
    </>
  );
}
