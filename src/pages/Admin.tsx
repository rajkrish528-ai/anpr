// ─────────────────────────────────────────────────────────────
// Admin page — vehicle records, manual check/exit, settings,
// active vehicles, slot navigation editor, log viewer, queue
// ─────────────────────────────────────────────────────────────
import React, { useEffect, useRef, useState } from "react";
import { Header } from "../Layout";
import { useLive, formatTime } from "../LiveContext";
import { api } from "../api";
import type {
  ActiveVehicle, AppSettings, DashboardStats, DirectionStep,
  LogStats, QueueEntry, SlotInfo, SystemLog, VehicleRecord,
} from "../types";
import { SystemSetup } from "./SystemSetup";

type Tab = "manual" | "data" | "active" | "slots" | "queue" | "logs" | "system" | "settings";
type Category = "Student" | "Faculty" | "Staff" | "Visitor";

const TIER_LABELS: Record<number, string> = {
  1: "Tier 1 — VIP",
  2: "Tier 2 — Faculty",
  3: "Tier 3 — Staff",
  4: "Tier 4 — Student",
  5: "Tier 5 — Visitor",
};

const LOG_LEVEL_COLORS: Record<string, string> = {
  DEBUG:    "#64748b",
  INFO:     "#22c55e",
  WARN:     "#f59e0b",
  ERROR:    "#ef4444",
  CRITICAL: "#a855f7",
};

interface VehicleForm {
  plate: string;
  name: string;
  category: Category;
  permit_tier: number;
}

interface SlotEditForm {
  path_description: string;
  floor: string;
  section: string;
  steps: DirectionStep[];
}

// ── Small helper components ────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="metric card">
      <small>{label}</small>
      <strong>{value}</strong>
    </article>
  );
}

function statusTag(status: string) {
  switch (status.toUpperCase()) {
    case "GRANTED":       return <span className="tag">Granted</span>;
    case "ALREADY_PARKED": return <span className="tag tag-reject">Already Parked</span>;
    case "NO_SLOT":       return <span className="tag tag-reject">No Slot</span>;
    case "QUEUED":        return <span className="tag" style={{ background: "#f59e0b22", color: "#f59e0b" }}>Queued</span>;
    case "QUEUE_ASSIGNED": return <span className="tag">Queue Assigned</span>;
    case "REJECTED":      return <span className="tag tag-reject">Rejected</span>;
    case "EXITED":        return <span className="tag tag-exit">Exited</span>;
    case "VERIFIED":      return <span className="tag" style={{ background: "#22c55e22", color: "#22c55e" }}>Verified</span>;
    case "OCR_FAILED":    return <span className="tag tag-reject">OCR Failed</span>;
    default:              return <span className="tag">{status}</span>;
  }
}

// ── Slot navigation editor sub-component ──────────────────────────────────────

function SlotEditor({
  slot, onSave, onClose,
}: {
  slot: SlotInfo;
  onSave: (slot_id: string, form: SlotEditForm) => Promise<void>;
  onClose: () => void;
}) {
  const [form, setForm] = useState<SlotEditForm>({
    path_description: slot.path_description || "",
    floor: slot.floor || "Ground",
    section: slot.section || "Main",
    steps: slot.directions_parsed || [],
  });
  const [saving, setSaving] = useState(false);

  const addStep = () =>
    setForm((f) => ({ ...f, steps: [...f.steps, { action: "straight", landmark: "" }] }));

  const removeStep = (i: number) =>
    setForm((f) => ({ ...f, steps: f.steps.filter((_, idx) => idx !== i) }));

  const updateStep = (i: number, key: keyof DirectionStep, value: string) =>
    setForm((f) => ({
      ...f,
      steps: f.steps.map((s, idx) => idx === i ? { ...s, [key]: value } : s),
    }));

  const handleSave = async () => {
    setSaving(true);
    await onSave(slot.slot_id, form);
    setSaving(false);
    onClose();
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000,
    }}>
      <div style={{
        background: "#fff", borderRadius: 16, padding: 32,
        width: "min(600px, 95vw)", maxHeight: "90vh", overflow: "auto",
        boxShadow: "0 24px 80px rgba(0,0,0,0.3)",
      }}>
        <h2 style={{ marginBottom: 4 }}>Edit Slot {slot.slot_id}</h2>
        <p style={{ color: "#666", marginBottom: 20, fontSize: 14 }}>
          Zone: {slot.zone} · Tier {slot.min_permit_tier}
        </p>

        <label style={{ display: "block", marginBottom: 16 }}>
          <span style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 6, color: "#555" }}>
            PATH DESCRIPTION
          </span>
          <textarea
            value={form.path_description}
            onChange={(e) => setForm({ ...form, path_description: e.target.value })}
            placeholder="e.g. Enter main gate → turn right → VIP Wing"
            rows={2}
            style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #ddd", resize: "vertical", fontFamily: "inherit" }}
          />
        </label>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
          <label>
            <span style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 6, color: "#555" }}>FLOOR</span>
            <input
              value={form.floor}
              onChange={(e) => setForm({ ...form, floor: e.target.value })}
              placeholder="e.g. Ground, Level 1"
              style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #ddd" }}
            />
          </label>
          <label>
            <span style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 6, color: "#555" }}>SECTION</span>
            <input
              value={form.section}
              onChange={(e) => setForm({ ...form, section: e.target.value })}
              placeholder="e.g. Block A, North"
              style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #ddd" }}
            />
          </label>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#555" }}>TURN-BY-TURN DIRECTIONS</span>
            <button
              type="button" onClick={addStep}
              style={{ fontSize: 12, padding: "4px 12px", background: "#f0fdf4", border: "1px solid #86efac", borderRadius: 6, cursor: "pointer", color: "#16a34a" }}
            >
              + Add step
            </button>
          </div>
          {form.steps.map((step, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
              <select
                value={step.action}
                onChange={(e) => updateStep(i, "action", e.target.value)}
                style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid #ddd", minWidth: 110 }}
              >
                <option value="straight">⬆ Straight</option>
                <option value="left">⬅ Left</option>
                <option value="right">➡ Right</option>
                <option value="arrive">📍 Arrive</option>
              </select>
              <input
                value={step.landmark}
                onChange={(e) => updateStep(i, "landmark", e.target.value)}
                placeholder="Landmark / instruction"
                style={{ flex: 1, padding: "6px 10px", borderRadius: 6, border: "1px solid #ddd" }}
              />
              <button
                type="button" onClick={() => removeStep(i)}
                style={{ color: "#ef4444", background: "none", border: "none", cursor: "pointer", fontSize: 16 }}
              >
                ×
              </button>
            </div>
          ))}
          {form.steps.length === 0 && (
            <p style={{ fontSize: 13, color: "#999", fontStyle: "italic" }}>No directions set. Click "+ Add step" to begin.</p>
          )}
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 24 }}>
          <button
            onClick={handleSave} disabled={saving}
            style={{
              flex: 1, padding: "10px", borderRadius: 8, background: "#1a4a2a",
              color: "#fff", border: "none", cursor: "pointer", fontWeight: 600,
            }}
          >
            {saving ? "Saving..." : "Save navigation info"}
          </button>
          <button
            onClick={onClose}
            style={{ padding: "10px 20px", borderRadius: 8, background: "#f5f5f5", border: "1px solid #ddd", cursor: "pointer" }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Admin component ───────────────────────────────────────────────────────

export function Admin() {
  const { result, history } = useLive();
  const [tab, setTab] = useState<Tab>("manual");
  const [form, setForm] = useState<VehicleForm>({ plate: "", name: "", category: "Student", permit_tier: 4 });
  const [exitPlate, setExitPlate] = useState("");
  const [settings, setSettings] = useState<AppSettings>({ campus_name: "Smart Campus", total_slots: 50 });
  const [records, setRecords] = useState<VehicleRecord[]>([]);
  const [activeVehicles, setActiveVehicles] = useState<ActiveVehicle[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [notice, setNotice] = useState("");

  // Slots tab
  const [slots, setSlots] = useState<SlotInfo[]>([]);
  const [editingSlot, setEditingSlot] = useState<SlotInfo | null>(null);

  // Queue tab
  const [queue, setQueue] = useState<QueueEntry[]>([]);

  // Logs tab
  const [logs, setLogs] = useState<SystemLog[]>([]);
  const [logStats, setLogStats] = useState<LogStats | null>(null);
  const [logLevel, setLogLevel] = useState<string>("all");
  const [logPlate, setLogPlate] = useState("");
  const logsRef = useRef<HTMLDivElement>(null);

  const loadAdminData = () =>
    Promise.all([
      api<VehicleRecord[]>("/vehicles"),
      api<AppSettings>("/settings"),
      api<ActiveVehicle[]>("/active"),
      api<DashboardStats>("/dashboard"),
    ])
      .then(([vehicles, saved, active, dashStats]) => {
        setRecords(vehicles);
        setSettings(saved);
        setActiveVehicles(active);
        setStats(dashStats);
      })
      .catch(() => setNotice("Unable to load admin data."));

  const loadSlots = () =>
    api<SlotInfo[]>("/slots").then((s) => {
      const enriched = s.map((slot) => ({
        ...slot,
        directions_parsed: (() => {
          try { return JSON.parse(slot.directions || "[]"); }
          catch { return []; }
        })(),
      }));
      setSlots(enriched);
    }).catch(() => {});

  const loadQueue = () =>
    api<QueueEntry[]>("/queue").then(setQueue).catch(() => {});

  const loadLogs = () => {
    const params = new URLSearchParams({ limit: "100" });
    if (logLevel !== "all") params.set("level", logLevel);
    if (logPlate.trim()) params.set("plate", logPlate.trim());
    Promise.all([
      api<SystemLog[]>(`/logs?${params}`),
      api<LogStats>("/logs/stats"),
    ]).then(([l, ls]) => {
      setLogs(l);
      setLogStats(ls);
    }).catch(() => {});
  };

  useEffect(() => {
    loadAdminData();
    const interval = setInterval(loadAdminData, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (tab === "slots") loadSlots();
    if (tab === "queue") {
      loadQueue();
      const t = setInterval(loadQueue, 3000);
      return () => clearInterval(t);
    }
    if (tab === "logs") loadLogs();
  }, [tab]);

  // ── Actions ──────────────────────────────────────────────────────────────────

  const manualCheck = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/results/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate: form.plate }),
      });
      setNotice("Manual result sent to every live display.");
      loadAdminData();
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const manualExit = async (plate: string) => {
    try {
      await api("/exit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate }),
      });
      setNotice(`Vehicle ${plate} exited successfully.`);
      setExitPlate("");
      loadAdminData();
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const addVehicle = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = { plate: form.plate, owner_name: form.name, category: form.category, permit_tier: form.permit_tier };
      const exists = records.some((r) => r.plate === form.plate);
      await api(exists ? `/vehicles/${form.plate}` : "/vehicles", {
        method: exists ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exists ? { owner_name: form.name, category: form.category, permit_tier: form.permit_tier } : payload),
      });
      setForm({ plate: "", name: "", category: "Student", permit_tier: 4 });
      setNotice(exists ? "Vehicle record updated." : "Vehicle record saved.");
      loadAdminData();
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const removeVehicle = async (plate: string) => {
    if (!window.confirm(`Delete ${plate}?`)) return;
    try {
      await api(`/vehicles/${plate}`, { method: "DELETE" });
      setNotice("Vehicle record deleted.");
      loadAdminData();
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const saveSlotInfo = async (slot_id: string, slotForm: SlotEditForm) => {
    await api(`/slots/${slot_id}/info`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path_description: slotForm.path_description,
        directions: slotForm.steps,
        floor: slotForm.floor,
        section: slotForm.section,
      }),
    });
    setNotice(`Slot ${slot_id} navigation updated.`);
    loadSlots();
  };

  const removeFromQueue = async (plate: string) => {
    try {
      await api(`/queue/${plate}`, { method: "DELETE" });
      setNotice(`${plate} removed from queue.`);
      loadQueue();
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const verifyParking = async (plate: string) => {
    try {
      await api("/parking/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate, source: "admin" }),
      });
      setNotice(`${plate} verified as parked.`);
      loadAdminData();
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const totalSlots = stats?.total_slots || result.totalSlots || settings.total_slots;
  const occupied   = stats?.occupied || result.occupied || 0;

  const TAB_LABELS: Record<Tab, string> = {
    manual:   "Manual check",
    data:     "Vehicle records",
    active:   "Active parking",
    slots:    "Parking slots",
    queue:    "Queue",
    logs:     "System logs",
    system:   "System config",
    settings: "Settings",
  };

  return (
    <>
      <Header title="Admin panel" note="Manage vehicle access, navigation, logs, and system settings." />

      <section className="metrics">
        <Metric label="Total bays" value={totalSlots} />
        <Metric label="Occupied" value={occupied} />
        <Metric label="Available" value={totalSlots - occupied} />
        <Metric label="Active vehicles" value={stats?.active_vehicles ?? 0} />
        <Metric label="Queue waiting" value={stats?.queue_waiting ?? 0} />
      </section>

      <section className="admin-tabs card">
        <div className="tab-list" style={{ flexWrap: "wrap" }}>
          {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {TAB_LABELS[t]}
              {t === "queue" && (stats?.queue_waiting ?? 0) > 0 && (
                <span style={{
                  marginLeft: 6, fontSize: 10, background: "#f59e0b",
                  color: "#fff", borderRadius: 10, padding: "1px 6px",
                }}>
                  {stats?.queue_waiting}
                </span>
              )}
            </button>
          ))}
        </div>

        {notice && <p className="api-notice">{notice}</p>}

        {/* ── Manual check ─────────────────────────────────── */}
        {tab === "manual" && (
          <div className="admin-content">
            <h2>Manual vehicle check</h2>
            <p>Use a plate number when the camera cannot read it.</p>
            <form className="inline-form" onSubmit={manualCheck}>
              <input
                required
                value={form.plate}
                onChange={(e) => setForm({ ...form, plate: e.target.value.toUpperCase() })}
                placeholder="e.g. BR01N2323"
              />
              <button className="primary">Check &amp; assign parking</button>
            </form>

            <h2 style={{ marginTop: "2rem" }}>Manual vehicle exit</h2>
            <p>Enter a plate number to exit a parked vehicle and release its slot.</p>
            <form className="inline-form" onSubmit={(e) => { e.preventDefault(); manualExit(exitPlate); }}>
              <input
                required
                value={exitPlate}
                onChange={(e) => setExitPlate(e.target.value.toUpperCase())}
                placeholder="e.g. BR01N2323"
              />
              <button className="primary">Exit vehicle</button>
            </form>

            <h2 style={{ marginTop: "2rem" }}>Mark vehicle as verified</h2>
            <p>Manually confirm a vehicle has physically parked in its assigned slot.</p>
            <form className="inline-form" onSubmit={(e) => { e.preventDefault(); const inp = (e.target as HTMLFormElement).plate.value; verifyParking(inp); }}>
              <input name="plate" placeholder="e.g. BR01N2323" required style={{ textTransform: "uppercase" }} />
              <button className="primary">Verify parked</button>
            </form>
          </div>
        )}

        {/* ── Vehicle records ───────────────────────────────── */}
        {tab === "data" && (
          <div className="admin-content">
            <h2>Add or edit vehicle record</h2>
            <p>Register vehicles with name, category, and permit tier.</p>
            <form className="data-form" onSubmit={addVehicle}>
              <label>
                Plate number
                <input required value={form.plate} onChange={(e) => setForm({ ...form, plate: e.target.value.toUpperCase() })} placeholder="BR01N2323" />
              </label>
              <label>
                Owner name
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Student or staff name" />
              </label>
              <label>
                Category
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as Category })}>
                  <option>Student</option>
                  <option>Faculty</option>
                  <option>Staff</option>
                  <option>Visitor</option>
                </select>
              </label>
              <label>
                Permit tier
                <select value={form.permit_tier} onChange={(e) => setForm({ ...form, permit_tier: +e.target.value })}>
                  <option value={1}>Tier 1 — VIP / Director</option>
                  <option value={2}>Tier 2 — Faculty</option>
                  <option value={3}>Tier 3 — Staff</option>
                  <option value={4}>Tier 4 — Student</option>
                  <option value={5}>Tier 5 — Visitor</option>
                </select>
              </label>
              <button className="primary">Save vehicle record</button>
            </form>
            <div className="records-list">
              {records.map((rec) => (
                <div key={rec.plate}>
                  <span className="mono">{rec.plate}</span>
                  <span>{rec.owner_name} · {rec.category} · {TIER_LABELS[rec.permit_tier] || `Tier ${rec.permit_tier}`}</span>
                  <button type="button" onClick={() => setForm({ plate: rec.plate, name: rec.owner_name, category: rec.category as Category, permit_tier: rec.permit_tier })}>Edit</button>
                  <button type="button" onClick={() => removeVehicle(rec.plate)}>Delete</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Active parking ────────────────────────────────── */}
        {tab === "active" && (
          <div className="admin-content">
            <h2>Currently parked vehicles</h2>
            <p>{activeVehicles.length} vehicle{activeVehicles.length !== 1 ? "s" : ""} currently on campus.</p>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", marginTop: "1rem" }}>
              <thead>
                <tr>
                  {["Plate", "Owner", "Category", "Slot", "Entry time", "Verified", "Actions"].map((h) => (
                    <th key={h} style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {activeVehicles.map((v) => (
                  <tr key={v.plate}>
                    <td className="mono" style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{v.plate}</td>
                    <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{v.owner_name}</td>
                    <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{v.category}</td>
                    <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}><b>{v.slot_id}</b></td>
                    <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{v.entry_time?.replace("T", " ").slice(0, 16)}</td>
                    <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>
                      {v.verified ? <span style={{ color: "#22c55e", fontWeight: 600 }}>✓</span> : <span style={{ color: "#f59e0b" }}>Pending</span>}
                    </td>
                    <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec", display: "flex", gap: 6 }}>
                      {!v.verified && <button type="button" onClick={() => verifyParking(v.plate)} style={{ fontSize: 12, padding: "4px 8px" }}>Verify</button>}
                      <button type="button" onClick={() => manualExit(v.plate)}>Exit</button>
                    </td>
                  </tr>
                ))}
                {activeVehicles.length === 0 && (
                  <tr><td colSpan={7} style={{ padding: "20px", textAlign: "center", color: "#718078" }}>No vehicles currently parked.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Parking slots nav editor ──────────────────────── */}
        {tab === "slots" && (
          <div className="admin-content">
            <h2>Parking slot navigation</h2>
            <p>Set per-slot directions and navigation details that appear on the result display.</p>
            <div style={{ overflowX: "auto", marginTop: "1rem" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr>
                    {["Slot", "Zone", "Tier", "Status", "Floor", "Section", "Path preview", "Directions", "Action"].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2", whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {slots.map((s) => (
                    <tr key={s.slot_id} style={{ background: s.status === "occupied" ? "#fff8f0" : "transparent" }}>
                      <td className="mono" style={{ padding: "8px", borderBottom: "1px solid #edf0ec", fontWeight: 700 }}>{s.slot_id}</td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>{s.zone}</td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>{s.min_permit_tier}</td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>
                        <span style={{ color: s.status === "available" ? "#22c55e" : "#ef4444", fontWeight: 600 }}>
                          {s.status}
                        </span>
                      </td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>{s.floor || "—"}</td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>{s.section || "—"}</td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {s.path_description || <span style={{ color: "#999", fontStyle: "italic" }}>Not set</span>}
                      </td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>
                        {(s.directions_parsed || []).length} steps
                      </td>
                      <td style={{ padding: "8px", borderBottom: "1px solid #edf0ec" }}>
                        <button type="button" onClick={() => setEditingSlot(s)} style={{ fontSize: 12, padding: "4px 10px" }}>
                          Edit nav
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Queue ────────────────────────────────────────── */}
        {tab === "queue" && (
          <div className="admin-content">
            <h2>Waiting queue</h2>
            <p>
              {queue.length === 0
                ? "No vehicles currently waiting."
                : `${queue.length} vehicle${queue.length !== 1 ? "s" : ""} in the waiting queue.`}
            </p>
            {queue.length > 0 && (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", marginTop: "1rem" }}>
                <thead>
                  <tr>
                    {["#", "Plate", "Owner", "Category", "Tier", "Joined at", "Action"].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {queue.map((q, i) => (
                    <tr key={q.plate}>
                      <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec", fontWeight: 700, color: "#f59e0b" }}>#{i + 1}</td>
                      <td className="mono" style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{q.plate}</td>
                      <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{q.owner_name}</td>
                      <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{q.category}</td>
                      <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{TIER_LABELS[q.permit_tier] || `Tier ${q.permit_tier}`}</td>
                      <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>{q.joined_at?.replace("T", " ").slice(0, 16)}</td>
                      <td style={{ padding: "10px 8px", borderBottom: "1px solid #edf0ec" }}>
                        <button type="button" onClick={() => removeFromQueue(q.plate)} style={{ color: "#ef4444", fontSize: 12 }}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* ── System logs ───────────────────────────────────── */}
        {tab === "logs" && (
          <div className="admin-content">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
              <div>
                <h2>System logs</h2>
                <p>Structured audit trail of all parking events.</p>
              </div>
              {logStats && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {(["INFO", "WARN", "ERROR", "CRITICAL"] as const).map((level) => {
                    const key = `today_${level.toLowerCase()}` as keyof LogStats;
                    const count = logStats[key] as number;
                    return count > 0 ? (
                      <span key={level} style={{
                        fontSize: 12, padding: "4px 10px", borderRadius: 12,
                        background: `${LOG_LEVEL_COLORS[level]}20`,
                        color: LOG_LEVEL_COLORS[level], fontWeight: 600,
                      }}>
                        {level}: {count}
                      </span>
                    ) : null;
                  })}
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 10, margin: "16px 0", flexWrap: "wrap" }}>
              <select
                value={logLevel}
                onChange={(e) => setLogLevel(e.target.value)}
                style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid #ddd" }}
              >
                <option value="all">All levels</option>
                <option value="DEBUG">Debug</option>
                <option value="INFO">Info</option>
                <option value="WARN">Warning</option>
                <option value="ERROR">Error</option>
                <option value="CRITICAL">Critical</option>
              </select>
              <input
                value={logPlate}
                onChange={(e) => setLogPlate(e.target.value.toUpperCase())}
                placeholder="Filter by plate..."
                style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid #ddd", width: 150 }}
              />
              <button
                className="primary"
                onClick={loadLogs}
                style={{ padding: "6px 16px" }}
              >
                Refresh
              </button>
            </div>

            <div ref={logsRef} style={{ maxHeight: 500, overflow: "auto" }}>
              {logs.length === 0 ? (
                <p style={{ color: "#999", fontStyle: "italic", padding: "20px" }}>No logs found.</p>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                  <thead style={{ position: "sticky", top: 0, background: "#fff" }}>
                    <tr>
                      {["Time", "Level", "Event", "Message", "Plate", "Slot", "Source"].map((h) => (
                        <th key={h} style={{ textAlign: "left", padding: "8px 8px", borderBottom: "2px solid #e4e8e2", whiteSpace: "nowrap" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((log) => (
                      <tr key={log.id} style={{ background: log.level === "ERROR" || log.level === "CRITICAL" ? "#fff5f5" : "transparent" }}>
                        <td style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0", whiteSpace: "nowrap", color: "#888" }}>
                          {log.created_at?.replace("T", " ").slice(0, 19)}
                        </td>
                        <td style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0" }}>
                          <span style={{
                            fontSize: 10, padding: "2px 7px", borderRadius: 8, fontWeight: 700,
                            background: `${LOG_LEVEL_COLORS[log.level] || "#888"}20`,
                            color: LOG_LEVEL_COLORS[log.level] || "#888",
                          }}>
                            {log.level}
                          </span>
                        </td>
                        <td style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0", color: "#666", whiteSpace: "nowrap" }}>
                          {log.event_type}
                        </td>
                        <td style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0" }}>{log.message}</td>
                        <td className="mono" style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0" }}>{log.plate || "—"}</td>
                        <td style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0" }}>{log.slot_id || "—"}</td>
                        <td style={{ padding: "7px 8px", borderBottom: "1px solid #f0f0f0", color: "#888" }}>{log.source || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* ── System config ─────────────────────────────────── */}
        {tab === "system" && (
          <div className="admin-content" style={{ marginTop: "2rem" }}>
            <SystemSetup />
          </div>
        )}

        {/* ── Settings ──────────────────────────────────────── */}
        {tab === "settings" && (
          <div className="admin-content">
            <h2>Account settings</h2>
            <form className="data-form" onSubmit={async (e) => {
              e.preventDefault();
              try {
                const saved = await api<AppSettings>("/settings", {
                  method: "PUT",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(settings),
                });
                setSettings(saved);
                setNotice("Settings saved to SQLite.");
              } catch (err) {
                setNotice((err as Error).message);
              }
            }}>
              <label>
                Campus name
                <input value={settings.campus_name} onChange={(e) => setSettings({ ...settings, campus_name: e.target.value })} />
              </label>
              <label>
                Total parking bays
                <input type="number" min="1" value={settings.total_slots} onChange={(e) => setSettings({ ...settings, total_slots: +e.target.value })} />
              </label>
              <button className="primary">Save settings</button>
              <button type="button" onClick={async () => {
                try { await api("/logout", { method: "POST" }); } catch (e) {}
                localStorage.removeItem("parking-admin-token");
                window.location.href = "/login";
              }}>
                Sign out
              </button>
            </form>
          </div>
        )}
      </section>

      {/* ── Live activity table ───────────────────────────── */}
      <section className="card table">
        <h2>Live activity</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Plate</th>
              <th>Driver</th>
              <th>Assignment</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {history.map((row, i) => (
              <tr key={`${row.timestamp}-${i}`}>
                <td>{formatTime(row.timestamp)}</td>
                <td className="mono">{row.plate_number}</td>
                <td>{row.studentName}</td>
                <td><b>{row.slot}</b> · {row.direction}</td>
                <td>{statusTag(row.status ?? "GRANTED")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* ── Slot editor modal ────────────────────────────────── */}
      {editingSlot && (
        <SlotEditor
          slot={editingSlot}
          onSave={saveSlotInfo}
          onClose={() => setEditingSlot(null)}
        />
      )}
    </>
  );
}
