// ─────────────────────────────────────────────────────────────
// ResultDisplay — rich driver-facing full-screen result with
// category-aware messaging, turn-by-turn directions, and live
// occupancy gauge.
// ─────────────────────────────────────────────────────────────
import React, { useEffect, useState } from "react";
import { useLive, formatTime } from "../LiveContext";
import type { DirectionStep } from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function categoryGreeting(category: string | undefined, name: string | undefined, status: string): string {
  const n = name || "Guest";
  switch (status) {
    case "QUEUED":
      return `Parking is currently full, ${n}.`;
    case "EXITED":
      return `Safe travels, ${n}! 👋`;
    case "ALREADY_PARKED":
      return `${n}, you are already parked.`;
    case "VERIFIED":
      return `Welcome, ${n}! Parking confirmed.`;
    case "QUEUE_ASSIGNED":
      return `Great news, ${n}! A slot just opened up.`;
    default:
      switch ((category || "").toLowerCase()) {
        case "faculty":
          return `Welcome, ${n}! Your reserved faculty spot is ready.`;
        case "staff":
          return `Welcome, ${n}! Staff parking has been assigned.`;
        case "student":
          return `Welcome, ${n}! Proceed to your student parking slot.`;
        case "visitor":
          return `Welcome! A visitor bay has been assigned for you.`;
        default:
          return `Welcome, ${n}! Your slot is assigned.`;
      }
  }
}

function categoryEmoji(category: string | undefined, status: string): string {
  if (status === "QUEUED") return "⏳";
  if (status === "EXITED") return "👋";
  if (status === "ALREADY_PARKED") return "🔴";
  if (status === "OCR_FAILED") return "⚠️";
  if (status === "NO_SLOT") return "🔴";
  if (status === "VERIFIED") return "✅";
  if (status === "QUEUE_ASSIGNED") return "🎉";
  switch ((category || "").toLowerCase()) {
    case "faculty": return "🎓";
    case "staff":   return "💼";
    case "student": return "📚";
    case "visitor": return "🏛️";
    default:        return "🟢";
  }
}

function categoryAccent(category: string | undefined, status: string): { bg: string; accent: string; text: string } {
  if (status === "QUEUED")        return { bg: "#1a1a2e", accent: "#e8a838", text: "#fff8e8" };
  if (status === "NO_SLOT")       return { bg: "#1a0a0a", accent: "#e84848", text: "#ffe8e8" };
  if (status === "ALREADY_PARKED") return { bg: "#1a1400", accent: "#d4a820", text: "#fff9e0" };
  if (status === "OCR_FAILED")    return { bg: "#1a0a0a", accent: "#e84848", text: "#ffe8e8" };
  if (status === "EXITED")        return { bg: "#0a1520", accent: "#4a9eff", text: "#e8f4ff" };
  if (status === "VERIFIED")      return { bg: "#0a1a0a", accent: "#00e676", text: "#e8fff0" };
  if (status === "QUEUE_ASSIGNED") return { bg: "#0a1520", accent: "#00e676", text: "#e8fff4" };
  switch ((category || "").toLowerCase()) {
    case "faculty": return { bg: "#0d0f2a", accent: "#7c6fff", text: "#f0eeff" };
    case "staff":   return { bg: "#0a1a0a", accent: "#00c853", text: "#e8ffe8" };
    case "student": return { bg: "#0d1a2a", accent: "#00b4d8", text: "#e8f6ff" };
    case "visitor": return { bg: "#1a0d2a", accent: "#e040fb", text: "#f8e8ff" };
    default:        return { bg: "#0a1a0a", accent: "#00e676", text: "#e8fff4" };
  }
}

const ACTION_ICONS: Record<string, string> = {
  straight: "⬆",
  left: "⬅",
  right: "➡",
  arrive: "📍",
};

const ACTION_LABELS: Record<string, string> = {
  straight: "Go straight",
  left: "Turn left",
  right: "Turn right",
  arrive: "You have arrived",
};

// ── Live clock ────────────────────────────────────────────────────────────────
function LiveClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span style={{ fontVariantNumeric: "tabular-nums" }}>
      {now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
    </span>
  );
}

// ── Occupancy gauge ───────────────────────────────────────────────────────────
function OccupancyGauge({ occupied, total }: { occupied: number; total: number }) {
  const pct = total > 0 ? Math.round((occupied / total) * 100) : 0;
  const color = pct > 85 ? "#e84848" : pct > 60 ? "#e8a838" : "#00e676";
  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, opacity: 0.7, marginBottom: 6 }}>
        <span>Parking Occupancy</span>
        <span>{occupied}/{total} ({pct}%)</span>
      </div>
      <div style={{ background: "rgba(255,255,255,0.1)", borderRadius: 8, height: 8, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", background: color,
          borderRadius: 8, transition: "width 0.6s ease, background 0.4s",
        }} />
      </div>
    </div>
  );
}

// ── Animated direction step ───────────────────────────────────────────────────
function DirectionCard({ step, index, isLast }: { step: DirectionStep; index: number; isLast: boolean }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 14,
      padding: "12px 0",
      borderBottom: isLast ? "none" : "1px solid rgba(255,255,255,0.08)",
      animation: `fadeSlideIn 0.4s ease ${index * 0.1}s both`,
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: "50%",
        background: isLast ? "rgba(0,230,118,0.2)" : "rgba(255,255,255,0.1)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 18, flexShrink: 0,
        border: isLast ? "2px solid rgba(0,230,118,0.5)" : "1px solid rgba(255,255,255,0.15)",
      }}>
        {ACTION_ICONS[step.action] || "•"}
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>
          {ACTION_LABELS[step.action] || step.action}
        </div>
        <div style={{ fontSize: 13, opacity: 0.7 }}>{step.landmark}</div>
      </div>
    </div>
  );
}

// ── Slot badge ────────────────────────────────────────────────────────────────
function SlotBadge({ slot, floor, section, accent }: {
  slot: string; floor?: string; section?: string; accent: string;
}) {
  return (
    <div style={{
      display: "inline-flex", flexDirection: "column", alignItems: "center",
      background: `${accent}18`, border: `2px solid ${accent}`,
      borderRadius: 16, padding: "16px 28px", minWidth: 140,
    }}>
      <span style={{ fontSize: 11, opacity: 0.7, letterSpacing: 2, textTransform: "uppercase" }}>
        SLOT
      </span>
      <span style={{
        fontSize: 48, fontWeight: 800, letterSpacing: 2, lineHeight: 1,
        color: accent,
      }}>
        {slot}
      </span>
      {(floor || section) && (
        <span style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
          {floor}{floor && section ? " · " : ""}{section}
        </span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function ResultDisplay() {
  const { result } = useLive();
  const status = result.status || "GRANTED";
  const { bg, accent, text } = categoryAccent(result.category, status);

  const directions: DirectionStep[] = Array.isArray(result.directions)
    ? result.directions
    : [];

  return (
    <main style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse at top left, ${accent}22 0%, ${bg} 55%)`,
      color: text,
      fontFamily: "'Inter', 'Segoe UI', sans-serif",
      display: "flex",
      flexDirection: "column",
    }}>
      {/* ── Top bar ───────────────────────────────────────── */}
      <header style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "16px 28px",
        background: "rgba(0,0,0,0.3)",
        backdropFilter: "blur(12px)",
        borderBottom: `1px solid ${accent}30`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 10, height: 10, borderRadius: "50%",
            background: accent,
            boxShadow: `0 0 8px ${accent}`,
            animation: "pulse 2s infinite",
          }} />
          <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 1, opacity: 0.9 }}>
            SMART PARKING SYSTEM
          </span>
        </div>
        <span style={{ fontSize: 14, opacity: 0.7 }}>
          <LiveClock />
        </span>
      </header>

      {/* ── Main content ───────────────────────────────────── */}
      <div style={{
        flex: 1, display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 0,
        minHeight: 0,
      }}>
        {/* ── Left: status panel ──────────────────────────── */}
        <section style={{
          padding: "40px 48px",
          display: "flex", flexDirection: "column", justifyContent: "center",
          borderRight: `1px solid rgba(255,255,255,0.06)`,
        }}>
          {/* Category emoji + greeting */}
          <div style={{ fontSize: 52, marginBottom: 16 }}>
            {categoryEmoji(result.category, status)}
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8, lineHeight: 1.2 }}>
            {categoryGreeting(result.category, result.studentName, status)}
          </h1>

          {/* Plate number */}
          {result.plate_number && (
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 12,
              background: "rgba(255,255,255,0.08)",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 10, padding: "10px 18px", marginTop: 16, marginBottom: 20,
              width: "fit-content",
            }}>
              <span style={{ fontSize: 12, opacity: 0.6, letterSpacing: 1.5, textTransform: "uppercase" }}>
                Plate
              </span>
              <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: 3 }}>
                {result.plate_number}
              </span>
              {result.category && (
                <span style={{
                  fontSize: 11, padding: "3px 8px", borderRadius: 6,
                  background: `${accent}30`, color: accent, fontWeight: 600,
                }}>
                  {result.category}
                </span>
              )}
            </div>
          )}

          {/* Status badge */}
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            fontSize: 13, fontWeight: 600, letterSpacing: 0.5,
            padding: "8px 14px", borderRadius: 8,
            background: status === "GRANTED" || status === "VERIFIED" || status === "QUEUE_ASSIGNED"
              ? "rgba(0,230,118,0.12)" : "rgba(255,255,255,0.08)",
            border: `1px solid ${accent}50`,
            width: "fit-content", marginBottom: 24,
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: accent, display: "inline-block",
            }} />
            {status === "GRANTED" ? "Access Granted" :
             status === "QUEUED" ? `Queued — Position #${result.queue_position || "?"}` :
             status === "QUEUE_ASSIGNED" ? "Slot Available — Proceed Now" :
             status === "ALREADY_PARKED" ? "Already Parked" :
             status === "EXITED" ? "Vehicle Departed" :
             status === "VERIFIED" ? "Parking Verified ✓" :
             status === "OCR_FAILED" ? "Plate Read Failed" :
             status === "NO_SLOT" ? "No Slots Available" :
             status}
          </div>

          {/* QUEUED: special messaging */}
          {status === "QUEUED" && (
            <div style={{
              background: "rgba(232,168,56,0.1)",
              border: "1px solid rgba(232,168,56,0.3)",
              borderRadius: 12, padding: "20px 24px",
            }}>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>
                You are in the waiting queue.
              </p>
              <p style={{ opacity: 0.8, fontSize: 14, lineHeight: 1.6 }}>
                A parking slot will be automatically assigned as soon as one becomes available.
                Please stay nearby and watch for your name on this screen.
              </p>
              {result.queue_waiting !== undefined && (
                <p style={{ marginTop: 12, fontSize: 13, opacity: 0.7 }}>
                  Vehicles in queue: <strong>{result.queue_waiting}</strong>
                </p>
              )}
            </div>
          )}

          {/* OCR failed guidance */}
          {status === "OCR_FAILED" && (
            <div style={{
              background: "rgba(232,72,72,0.1)",
              border: "1px solid rgba(232,72,72,0.3)",
              borderRadius: 12, padding: "20px 24px",
            }}>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>License plate could not be read.</p>
              <p style={{ opacity: 0.8, fontSize: 14 }}>
                Please move the vehicle closer to the camera or adjust position for a clearer view.
              </p>
            </div>
          )}

          {/* Occupancy gauge */}
          {result.occupied !== undefined && result.totalSlots !== undefined && (
            <OccupancyGauge occupied={result.occupied} total={result.totalSlots} />
          )}

          {/* Timestamp */}
          {result.timestamp && (
            <p style={{ marginTop: 20, fontSize: 12, opacity: 0.45 }}>
              Processed at {formatTime(result.timestamp)}
            </p>
          )}
        </section>

        {/* ── Right: slot + navigation panel ─────────────── */}
        <section style={{
          padding: "40px 48px",
          display: "flex", flexDirection: "column",
          overflow: "auto",
        }}>
          {/* Slot assignment */}
          {result.slot && result.slot !== "QUEUED" && status !== "OCR_FAILED" && (
            <div style={{ marginBottom: 32 }}>
              <p style={{ fontSize: 12, opacity: 0.5, letterSpacing: 2, textTransform: "uppercase", marginBottom: 16 }}>
                Assigned Slot
              </p>
              <SlotBadge
                slot={result.slot}
                floor={result.floor}
                section={result.section}
                accent={accent}
              />
            </div>
          )}

          {/* Path description */}
          {result.path_description && status !== "QUEUED" && status !== "OCR_FAILED" && (
            <div style={{ marginBottom: 24 }}>
              <p style={{ fontSize: 12, opacity: 0.5, letterSpacing: 2, textTransform: "uppercase", marginBottom: 8 }}>
                Route
              </p>
              <p style={{
                fontSize: 15, lineHeight: 1.6,
                background: "rgba(255,255,255,0.05)",
                borderRadius: 10, padding: "14px 18px",
                border: "1px solid rgba(255,255,255,0.08)",
              }}>
                {result.path_description}
              </p>
            </div>
          )}

          {/* Turn-by-turn directions */}
          {directions.length > 0 && status !== "QUEUED" && status !== "OCR_FAILED" && (
            <div>
              <p style={{ fontSize: 12, opacity: 0.5, letterSpacing: 2, textTransform: "uppercase", marginBottom: 8 }}>
                Directions
              </p>
              <div style={{
                background: "rgba(255,255,255,0.04)",
                borderRadius: 12, padding: "8px 16px",
                border: "1px solid rgba(255,255,255,0.08)",
              }}>
                {directions.map((step, i) => (
                  <DirectionCard
                    key={i}
                    step={step}
                    index={i}
                    isLast={i === directions.length - 1}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Exit info */}
          {status === "EXITED" && result.direction && (
            <div style={{
              background: "rgba(74,158,255,0.08)",
              border: "1px solid rgba(74,158,255,0.2)",
              borderRadius: 12, padding: "20px 24px", marginTop: 16,
            }}>
              <p style={{ fontWeight: 600, marginBottom: 4 }}>Slot Released</p>
              <p style={{ opacity: 0.8, fontSize: 14 }}>{result.direction}</p>
            </div>
          )}

          {/* Already parked info */}
          {status === "ALREADY_PARKED" && (
            <div style={{
              background: "rgba(212,168,32,0.08)",
              border: "1px solid rgba(212,168,32,0.2)",
              borderRadius: 12, padding: "20px 24px",
            }}>
              <p style={{ fontWeight: 600, marginBottom: 4 }}>Vehicle Currently Parked</p>
              <p style={{ fontSize: 24, fontWeight: 800, letterSpacing: 2, margin: "10px 0" }}>
                {result.slot}
              </p>
              {result.direction && (
                <p style={{ opacity: 0.7, fontSize: 13 }}>
                  {result.direction.replace("Already parked since ", "Since: ")}
                </p>
              )}
            </div>
          )}
        </section>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.85); }
        }
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateX(-12px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </main>
  );
}
