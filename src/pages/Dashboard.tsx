// ─────────────────────────────────────────────────────────────
// Dashboard page
// ─────────────────────────────────────────────────────────────
import React from "react";
import { Header } from "../Layout";
import { useLive } from "../LiveContext";

interface LaunchCardProps {
  icon: string;
  title: string;
  text: string;
  action: string;
  onClick: () => void;
}

function LaunchCard({ icon, title, text, action, onClick }: LaunchCardProps) {
  return (
    <article className="card launch-card">
      <span>{icon}</span>
      <h2>{title}</h2>
      <p>{text}</p>
      <button className="primary" onClick={onClick}>
        {action} ↗
      </button>
    </article>
  );
}

export function Dashboard() {
  const { result } = useLive();
  const open = (path: string) =>
    window.open(path, "_blank", "noopener,noreferrer");

  return (
    <>
      <Header
        title="Parking control dashboard"
        note="Open each operational screen in its own browser tab or display."
      />
      <section className="launch-grid">
        <LaunchCard
          icon="◉"
          title="Gate camera preview"
          text="Raw entry feed and its YOLO/OCR result."
          action="Open gate screen"
          onClick={() => open("/gate-camera-preview")}
        />
        <LaunchCard
          icon="▧"
          title="Parking camera preview"
          text="Parking-area feed and its YOLO/OCR result."
          action="Open parking screen"
          onClick={() => open("/parking-camera-preview")}
        />
        <LaunchCard
          icon="▣"
          title="Result display"
          text={`Current assignment: ${result.slot || "waiting"}. Designed for driver-facing display.`}
          action="Open result screen"
          onClick={() => open("/result")}
        />
        <LaunchCard
          icon="⚙"
          title="System setup"
          text="Configure cameras, ANPR pipeline, and recognition settings."
          action="Open setup"
          onClick={() => open("/setup")}
        />
      </section>
      <section className="card dashboard-status">
        <p className="eyebrow">LATEST LIVE ASSIGNMENT</p>
        <h2>
          {result.plate} <span>→</span> {result.slot}
        </h2>
        <p>
          {result.studentName} · {result.direction}
        </p>
      </section>
    </>
  );
}
