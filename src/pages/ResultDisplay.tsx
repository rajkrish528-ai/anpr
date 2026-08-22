// ─────────────────────────────────────────────────────────────
// ResultDisplay page — driver-facing full-screen result
// ─────────────────────────────────────────────────────────────
import React from "react";
import { useLive, formatTime } from "../LiveContext";

export function ResultDisplay() {
  const { result } = useLive();
  const status = result.status || "granted";

  let headerIcon = "✓";
  let headerTitle = "ACCESS GRANTED";
  let message = "Your vehicle was recognised successfully. Please follow the route shown below.";
  let bgClass = "welcome"; // default green

  if (status === "already_parked") {
    headerIcon = "!";
    headerTitle = "ALREADY PARKED";
    message = "Our records show this vehicle is already inside the campus.";
    bgClass = "welcome warning"; // we might need to add CSS for this, or just use existing
  } else if (status === "no_slot") {
    headerIcon = "✕";
    headerTitle = "PARKING FULL";
    message = "Sorry, no parking slots are currently available for your permit tier.";
    bgClass = "welcome error";
  } else if (status === "exited") {
    headerIcon = "👋";
    headerTitle = "GOODBYE";
    message = "Thank you for visiting. Have a safe journey!";
    bgClass = "welcome neutral";
  }

  // Define some inline styles for the different states if they don't exist in CSS
  const getStyleForStatus = () => {
    if (status === "already_parked") return { backgroundColor: "#8a6d3b", color: "#fcf8e3" };
    if (status === "no_slot") return { backgroundColor: "#a94442", color: "#f2dede" };
    if (status === "exited") return { backgroundColor: "#31708f", color: "#d9edf7" };
    return {}; // use default from CSS
  };

  const getCheckStyle = () => {
    if (status === "already_parked") return { backgroundColor: "#f0ad4e", color: "#fff" };
    if (status === "no_slot") return { backgroundColor: "#d9534f", color: "#fff" };
    if (status === "exited") return { backgroundColor: "#5bc0de", color: "#fff" };
    return {};
  };

  return (
    <main className="result-window">
      <section className={bgClass} style={getStyleForStatus()}>
        <div className="check" style={getCheckStyle()}>{headerIcon}</div>
        <p className="eyebrow" style={status !== 'granted' ? { color: 'rgba(255,255,255,0.8)' } : {}}>{headerTitle}</p>
        <h2>{status === "exited" ? "Goodbye" : "Welcome"}, {result.studentName || "visitor"}.</h2>
        <p style={status !== 'granted' ? { color: 'rgba(255,255,255,0.9)' } : {}}>
          {message}
        </p>
        <div className="assignment">
          <div>
            <small style={status !== 'granted' ? { color: 'rgba(255,255,255,0.7)' } : {}}>YOUR PARKING SPACE</small>
            <strong style={status !== 'granted' ? { color: '#fff' } : {}}>{result.slot || "—"}</strong>
          </div>
          <div>
            <small style={status !== 'granted' ? { color: 'rgba(255,255,255,0.7)' } : {}}>DIRECTION</small>
            <b style={status !== 'granted' ? { color: '#fff' } : {}}>↗ {result.direction || "Awaiting assignment"}</b>
            <span style={status !== 'granted' ? { color: 'rgba(255,255,255,0.7)' } : {}}>
              Plate {result.plate || "unread"} · {formatTime(result.timestamp)}
            </span>
          </div>
        </div>
      </section>

      <section className="two">
        <article className="card">
          <h3>Recognition details</h3>
          <dl>
            <dt>License plate</dt>
            <dd>{result.plate || "—"}</dd>
            <dt>Account</dt>
            <dd>{result.category || "Guest"}</dd>
            <dt>ANPR confidence</dt>
            <dd>{Math.round((result.confidence || 0) * 100)}%</dd>
          </dl>
        </article>
        {status === "granted" && (
          <article className="card map">
            <h3>Route overview</h3>
            <div className="road">
              <span className="car">●</span>
              <i />
              <b>{result.slot || "S2"}</b>
            </div>
            <p>
              Please proceed to your assigned parking zone.
            </p>
          </article>
        )}
        {status !== "granted" && (
          <article className="card map" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <p style={{ textAlign: 'center', color: '#6d7772', fontSize: '18px' }}>
              {status === "exited" ? "Have a great day!" : "Please contact security if you need assistance."}
            </p>
          </article>
        )}
      </section>
    </main>
  );
}
