// ─────────────────────────────────────────────────────────────
// Admin page — vehicle records, manual check/exit, settings, active vehicles
// ─────────────────────────────────────────────────────────────
import React, { useEffect, useState } from "react";
import { Header } from "../Layout";
import { useLive, formatTime } from "../LiveContext";
import { api } from "../api";
import type { ActiveVehicle, AppSettings, DashboardStats, VehicleRecord } from "../types";
import { SystemSetup } from "./SystemSetup";

type Tab = "manual" | "data" | "active" | "system" | "settings";
type Category = "Student" | "Faculty" | "Staff" | "Visitor";

const TIER_LABELS: Record<number, string> = {
  1: "Tier 1 — VIP",
  2: "Tier 2 — Faculty",
  3: "Tier 3 — Staff",
  4: "Tier 4 — Student",
  5: "Tier 5 — Visitor",
};

interface VehicleForm {
  plate: string;
  name: string;
  category: Category;
  permit_tier: number;
}

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
    case "GRANTED":
      return <span className="tag">Granted</span>;
    case "ALREADY_PARKED":
      return <span className="tag tag-reject">Already Parked</span>;
    case "NO_SLOT":
      return <span className="tag tag-reject">No Slot</span>;
    case "REJECTED":
      return <span className="tag tag-reject">Rejected</span>;
    case "EXITED":
      return <span className="tag tag-exit">Exited</span>;
    case "OCR_FAILED":
      return <span className="tag tag-reject">OCR Failed</span>;
    default:
      return <span className="tag">{status}</span>;
  }
}

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

  useEffect(() => {
    loadAdminData();
    const interval = setInterval(loadAdminData, 5000);
    return () => clearInterval(interval);
  }, []);

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
      const payload = {
        plate: form.plate,
        owner_name: form.name,
        category: form.category,
        permit_tier: form.permit_tier,
      };
      const exists = records.some((r) => r.plate === form.plate);
      await api(exists ? `/vehicles/${form.plate}` : "/vehicles", {
        method: exists ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          exists
            ? { owner_name: form.name, category: form.category, permit_tier: form.permit_tier }
            : payload
        ),
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

  const totalSlots = stats?.total_slots || result.totalSlots || settings.total_slots;
  const occupied = stats?.occupied || result.occupied || 0;

  return (
    <>
      <Header title="Admin page" note="Manage vehicle access, parking, and system settings." />

      <section className="metrics">
        <Metric label="Total bays" value={totalSlots} />
        <Metric label="Occupied" value={occupied} />
        <Metric label="Available" value={totalSlots - occupied} />
        <Metric label="Active vehicles" value={stats?.active_vehicles ?? 0} />
      </section>

      <section className="admin-tabs card">
        <div className="tab-list">
          {(["manual", "data", "active", "system", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t === "manual"
                ? "Manual check"
                : t === "data"
                ? "Vehicle records"
                : t === "active"
                ? "Active parking"
                : t === "system"
                ? "System config"
                : "Account settings"}
            </button>
          ))}
        </div>

        {notice && <p className="api-notice">{notice}</p>}

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
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                manualExit(exitPlate);
              }}
            >
              <input
                required
                value={exitPlate}
                onChange={(e) => setExitPlate(e.target.value.toUpperCase())}
                placeholder="e.g. BR01N2323"
              />
              <button className="primary">Exit vehicle</button>
            </form>
          </div>
        )}

        {tab === "data" && (
          <div className="admin-content">
            <h2>Add or edit vehicle record</h2>
            <p>Register vehicles with name, category, and permit tier.</p>
            <form className="data-form" onSubmit={addVehicle}>
              <label>
                Plate number
                <input
                  required
                  value={form.plate}
                  onChange={(e) => setForm({ ...form, plate: e.target.value.toUpperCase() })}
                  placeholder="BR01N2323"
                />
              </label>
              <label>
                Owner name
                <input
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Student or staff name"
                />
              </label>
              <label>
                Category
                <select
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value as Category })}
                >
                  <option>Student</option>
                  <option>Faculty</option>
                  <option>Staff</option>
                  <option>Visitor</option>
                </select>
              </label>
              <label>
                Permit tier
                <select
                  value={form.permit_tier}
                  onChange={(e) => setForm({ ...form, permit_tier: +e.target.value })}
                >
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
                  <span>
                    {rec.owner_name} · {rec.category} · {TIER_LABELS[rec.permit_tier] || `Tier ${rec.permit_tier}`}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setForm({
                        plate: rec.plate,
                        name: rec.owner_name,
                        category: rec.category as Category,
                        permit_tier: rec.permit_tier,
                      })
                    }
                  >
                    Edit
                  </button>
                  <button type="button" onClick={() => removeVehicle(rec.plate)}>
                    Delete
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "active" && (
          <div className="admin-content">
            <h2>Currently parked vehicles</h2>
            <p>{activeVehicles.length} vehicle{activeVehicles.length !== 1 ? "s" : ""} currently in the campus.</p>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", marginTop: "1rem" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>Plate</th>
                  <th style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>Owner</th>
                  <th style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>Category</th>
                  <th style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>Slot</th>
                  <th style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>Entry time</th>
                  <th style={{ textAlign: "left", padding: "10px 8px", borderBottom: "1px solid #e4e8e2" }}>Action</th>
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
                      <button type="button" onClick={() => manualExit(v.plate)}>
                        Exit
                      </button>
                    </td>
                  </tr>
                ))}
                {activeVehicles.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: "20px", textAlign: "center", color: "#718078" }}>
                      No vehicles currently parked.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === "system" && (
          <div className="admin-content" style={{ marginTop: '2rem' }}>
            <SystemSetup />
          </div>
        )}

        {tab === "settings" && (
          <div className="admin-content">
            <h2>Account settings</h2>
            <form
              className="data-form"
              onSubmit={async (e) => {
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
              }}
            >
              <label>
                Campus name
                <input
                  value={settings.campus_name}
                  onChange={(e) => setSettings({ ...settings, campus_name: e.target.value })}
                />
              </label>
              <label>
                Total parking bays
                <input
                  type="number"
                  min="1"
                  value={settings.total_slots}
                  onChange={(e) => setSettings({ ...settings, total_slots: +e.target.value })}
                />
              </label>
              <button className="primary">Save settings</button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await api("/logout", { method: "POST" });
                  } catch (e) {}
                  localStorage.removeItem("parking-admin-token");
                  window.location.href = "/login";
                }}
              >
                Sign out
              </button>
            </form>
          </div>
        )}
      </section>

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
                <td>
                  <b>{row.slot}</b> · {row.direction}
                </td>
                <td>{statusTag(row.status ?? "granted")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
