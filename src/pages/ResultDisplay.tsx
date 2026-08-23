// ─────────────────────────────────────────────────────────────
// ResultDisplay page — driver-facing full-screen result
// ─────────────────────────────────────────────────────────────
import React from "react";
import { useLive, formatTime } from "../LiveContext";

export function ResultDisplay() {
  const { result } = useLive();
  const status = result.status || "GRANTED";
  
  let headerIcon = "🟢";
  let headerTitle = "VEHICLE DETECTED";
  let bgClass = "welcome"; 

  if (status === "ALREADY_PARKED") {
    headerIcon = "🔴";
    headerTitle = "ALREADY PARKED";
    bgClass = "welcome warning";
  } else if (status === "NO_SLOT") {
    headerIcon = "🔴";
    headerTitle = "PARKING FULL";
    bgClass = "welcome error";
  } else if (status === "EXITED") {
    headerIcon = "👋";
    headerTitle = "VEHICLE DEPARTED";
    bgClass = "welcome neutral";
  } else if (status === "OCR_FAILED") {
    headerIcon = "⚠";
    headerTitle = "LICENSE PLATE DETECTED";
    bgClass = "welcome error";
  }

  const getStyleForStatus = () => {
    if (status === "ALREADY_PARKED") return { backgroundColor: "#8a6d3b", color: "#fcf8e3" };
    if (status === "NO_SLOT" || status === "OCR_FAILED") return { backgroundColor: "#a94442", color: "#f2dede" };
    if (status === "EXITED") return { backgroundColor: "#31708f", color: "#d9edf7" };
    return {};
  };

  return (
    <main className="result-window">
      <section className={bgClass} style={getStyleForStatus()}>
        <h2>{headerIcon} {headerTitle}</h2>

        <div style={{ marginTop: '20px', fontSize: '20px' }}>
          {status === "OCR_FAILED" ? (
            <>
              <div style={{ marginBottom: '15px' }}>
                <span style={{ opacity: 0.8, display: 'block', fontSize: '16px' }}>OCR:</span>
                <strong>Unable to read registration number</strong>
              </div>
              <p style={{ fontSize: '16px', opacity: 0.9 }}>
                Please move the vehicle closer or adjust the camera.
              </p>
            </>
          ) : (
            <>
              <div style={{ marginBottom: '15px' }}>
                <span style={{ opacity: 0.8, display: 'block', fontSize: '16px', textTransform: 'uppercase' }}>License Plate</span>
                <strong style={{ fontSize: '32px', letterSpacing: '2px' }}>{result.plate_number || "—"}</strong>
              </div>

              {status === "ALREADY_PARKED" && (
                <>
                  <div style={{ marginBottom: '15px' }}>
                    <span style={{ opacity: 0.8, display: 'block', fontSize: '16px', textTransform: 'uppercase' }}>Assigned Slot</span>
                    <strong style={{ fontSize: '28px' }}>{result.slot}</strong>
                  </div>
                  <div style={{ marginBottom: '15px' }}>
                    <span style={{ opacity: 0.8, display: 'block', fontSize: '16px', textTransform: 'uppercase' }}>Entry Time</span>
                    <strong style={{ fontSize: '24px' }}>{result.direction?.replace('Already parked since ', '') || "—"}</strong>
                  </div>
                </>
              )}

              {status !== "ALREADY_PARKED" && (
                <>
                  <div style={{ marginBottom: '15px' }}>
                    <span style={{ opacity: 0.8, display: 'block', fontSize: '16px' }}>OCR</span>
                    <strong>{result.ocr_success ? "✓ Successfully Read" : "Failed"}</strong>
                  </div>
                  
                  <div style={{ marginBottom: '15px' }}>
                    <span style={{ opacity: 0.8, display: 'block', fontSize: '16px' }}>YOLO Confidence</span>
                    <strong>{Math.round((result.yolo_confidence || 0) * 100)}%</strong>
                  </div>

                  <div style={{ marginBottom: '15px' }}>
                    <span style={{ opacity: 0.8, display: 'block', fontSize: '16px' }}>Status</span>
                    <strong>{status === 'GRANTED' ? '🟢 GRANTED' : status}</strong>
                  </div>

                  {status === "GRANTED" && (
                    <div style={{ marginBottom: '15px' }}>
                      <span style={{ opacity: 0.8, display: 'block', fontSize: '16px' }}>Parking Slot</span>
                      <strong style={{ fontSize: '32px' }}>{result.slot}</strong>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </section>

      <section className="two">
        <article className="card">
          <h3>Recognition details</h3>
          <dl>
            <dt>License plate</dt>
            <dd>{result.plate_number || "—"}</dd>
            <dt>Account</dt>
            <dd>{result.category || "Guest"}</dd>
            <dt>ANPR confidence</dt>
            <dd>{Math.round((result.yolo_confidence || 0) * 100)}%</dd>
          </dl>
        </article>
        {status === "GRANTED" && (
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
      </section>
    </main>
  );
}

