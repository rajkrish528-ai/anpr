// ─────────────────────────────────────────────────────────────
// Shared layout components: Header, Shell
// ─────────────────────────────────────────────────────────────
import React from "react";
import { NavLink } from "react-router-dom";
import { useLive } from "./LiveContext";

interface HeaderProps {
  title: string;
  note?: string;
}

export function Header({ title, note }: HeaderProps) {
  const { status } = useLive();
  return (
    <header>
      <div>
        <p className="eyebrow">SMART CAMPUS · PARKING CONTROL</p>
        <h1>{title}</h1>
        {note && <p className="muted">{note}</p>}
      </div>
      <div className={`connection ${status}`}>
        <i />
        {status === "live" ? "WebSocket live" : "Reconnecting…"}
      </div>
    </header>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <aside>
        <NavLink className="brand" to="/">
          <span>⌁</span> Parkwise
        </NavLink>
        <nav>
          <NavLink to="/">▦ Dashboard</NavLink>
          <NavLink to="/gate-camera-preview">◉ Gate camera</NavLink>
          <NavLink to="/parking-camera-preview">▧ Parking camera</NavLink>
          <NavLink to="/result">▣ Result display</NavLink>
          <NavLink to="/test-image">📷 Test Image</NavLink>
          <NavLink to="/admin">☰ Admin Panel</NavLink>
        </nav>
        <div className="side-footer">
          <span className="pulse" /> ANPR service online
        </div>
      </aside>
      <main>{children}</main>
    </div>
  );
}
