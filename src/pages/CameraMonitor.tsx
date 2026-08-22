// ─────────────────────────────────────────────────────────────
// CameraMonitor — full-screen YOLO-processed stream
// ─────────────────────────────────────────────────────────────
import React from "react";
import { useLive } from "../LiveContext";

interface CameraMonitorProps {
  source: string;
  label: string;
}

export function CameraMonitor({ source, label }: CameraMonitorProps) {
  const { frames, status } = useLive();
  return (
    <div className="camera-monitor">
      {frames[source] ? (
        <img src={frames[source]} alt={`${label} processed stream`} />
      ) : (
        <div className="monitor-empty" />
      )}
      <div className="monitor-overlay top">
        <b>{label}</b>
        <span>YOLO PROCESSED</span>
      </div>
      <div className="monitor-overlay bottom">
        <span className={`monitor-dot${status === "live" ? " live" : ""}`} />
        {status === "live" ? "LIVE · WEBSOCKET" : "CONNECTING…"}
      </div>
    </div>
  );
}
