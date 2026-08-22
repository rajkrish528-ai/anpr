// ─────────────────────────────────────────────────────────────
// ResultDisplay page — driver-facing full-screen result
// ─────────────────────────────────────────────────────────────
import React from "react";
import { useLive, formatTime } from "../LiveContext";

export function ResultDisplay() {
  const { result } = useLive();
  return (
    <main className="result-window">
      <section className="welcome">
        <div className="check">✓</div>
        <p className="eyebrow">ACCESS GRANTED</p>
        <h2>Welcome, {result.studentName || "visitor"}.</h2>
        <p>
          Your vehicle was recognised successfully. Please follow the route
          shown below.
        </p>
        <div className="assignment">
          <div>
            <small>YOUR PARKING SPACE</small>
            <strong>{result.slot || "—"}</strong>
          </div>
          <div>
            <small>DRIVE TO</small>
            <b>↗ {result.direction || "Awaiting assignment"}</b>
            <span>
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
        <article className="card map">
          <h3>Route overview</h3>
          <div className="road">
            <span className="car">●</span>
            <i />
            <b>{result.slot || "S2"}</b>
          </div>
          <p>
            Enter via Gate A, continue straight, and turn right at East Wing.
          </p>
        </article>
      </section>
    </main>
  );
}
