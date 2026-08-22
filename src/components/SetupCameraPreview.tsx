// ─────────────────────────────────────────────────────────────
// SetupCameraPreview — WebSocket raw-stream preview widget
// Used inside the SystemSetup config card.
// Opens /ws/camera/preview/{deviceIndex} and renders frames.
// ─────────────────────────────────────────────────────────────
import React, { useEffect, useRef, useState } from "react";
import { WS_BASE } from "../api";

type PreviewStatus = "connecting" | "live" | "error" | "closed" | "no-camera";

const STATUS_LABEL: Record<PreviewStatus, string> = {
  connecting: "Connecting…",
  live: "LIVE",
  error: "Camera unavailable",
  closed: "Disconnected",
  "no-camera": "Select a camera",
};

const STATUS_ICON: Record<PreviewStatus, string> = {
  connecting: "⟳",
  live: "●",
  error: "⚠",
  closed: "○",
  "no-camera": "—",
};

interface Props {
  deviceIndex: number;
  label: string;
}

export function SetupCameraPreview({ deviceIndex, label }: Props) {
  const [frame, setFrame] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<PreviewStatus>("no-camera");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Close any existing socket
    wsRef.current?.close();
    wsRef.current = null;

    if (deviceIndex < 0) {
      setFrame(null);
      setWsStatus("no-camera");
      return;
    }

    setFrame(null);
    setWsStatus("connecting");

    const url = `${WS_BASE}/ws/camera/preview/${deviceIndex}`;
    const socket = new WebSocket(url);
    wsRef.current = socket;

    socket.onopen = () => setWsStatus("connecting");

    socket.onmessage = ({ data }: MessageEvent<string>) => {
      try {
        const msg = JSON.parse(data) as { type: string; image?: string; status?: string };
        if (msg.type === "preview_frame" && msg.image) {
          setFrame(msg.image);
          setWsStatus("live");
        }
        if (msg.type === "preview_status") {
          if (msg.status === "error") {
            setWsStatus("error");
            setFrame(null);
          }
          else if (msg.status === "streaming") setWsStatus("live");
        }
      } catch {
        // ignore
      }
    };

    socket.onclose = () => {
      setWsStatus("closed");
      setFrame(null);
    };
    socket.onerror = () => {
      setWsStatus("error");
      socket.close();
    };

    return () => {
      socket.close();
      wsRef.current = null;
    };
  }, [deviceIndex]);

  return (
    <div className="setup-preview-ws">
      {frame ? (
        <img src={frame} alt={`${label} live preview`} />
      ) : (
        <div className="setup-preview-placeholder">
          <span>{STATUS_ICON[wsStatus]}</span>
          <small>{STATUS_LABEL[wsStatus]}</small>
        </div>
      )}
      <div className="setup-preview-bar">
        <b>{label}</b>
        <span className={`preview-dot${wsStatus === "live" ? " live" : ""}`} />
        <span>{STATUS_LABEL[wsStatus]}</span>
      </div>
    </div>
  );
}
