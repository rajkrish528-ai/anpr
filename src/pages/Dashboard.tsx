// ─────────────────────────────────────────────────────────────
// Dashboard page — real-time metrics + launch cards
// ─────────────────────────────────────────────────────────────
import React, { useEffect, useState } from "react";
import { Header } from "../Layout";
import { useLive } from "../LiveContext";
import { api } from "../api";
import type { DashboardStats } from "../types";

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

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="metric card">
      <small>{label}</small>
      <strong>{value}</strong>
    </article>
  );
}

export function Dashboard() {
  const { result } = useLive();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const open = (path: string) =>
    window.open(path, "_blank", "noopener,noreferrer");

  useEffect(() => {
    const load = () =>
      api<DashboardStats>("/dashboard")
        .then(setStats)
        .catch(() => {});
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  // Use live WS data if available, fall back to polled stats
  const totalSlots = result.totalSlots || stats?.total_slots || 50;
  const occupied = result.occupied || stats?.occupied || 0;
  const available = totalSlots - occupied;

  return (
    <>
      <Header
        title="Parking control dashboard"
        note="Real-time campus parking overview and operational screens."
      />

      <section className="metrics">
        <Metric label="Total bays" value={totalSlots} />
        <Metric label="Occupied" value={occupied} />
        <Metric label="Available" value={available} />
        <Metric label="Today's entries" value={stats?.today_entries ?? "—"} />
        <Metric label="Active vehicles" value={stats?.active_vehicles ?? "—"} />
        <Metric label="Today's exits" value={stats?.today_exits ?? "—"} />
      </section>

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
          {result.plate_number} <span>→</span> {result.slot}
        </h2>
        <p>
          {result.studentName} · {result.direction} ·{" "}
          <span className={`tag ${result.status === "granted" ? "" : result.status === "exited" ? "tag-exit" : "tag-reject"}`}>
            {result.status === "granted"
              ? "Granted"
              : result.status === "already_parked"
              ? "Already Parked"
              : result.status === "no_slot"
              ? "No Slot"
              : result.status === "exited"
              ? "Exited"
              : result.status ?? "Granted"}
          </span>
        </p>
      </section>
    </>
  );
}
