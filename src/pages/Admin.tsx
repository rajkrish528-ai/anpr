// ─────────────────────────────────────────────────────────────
// Admin page — vehicle records, manual check, settings
// ─────────────────────────────────────────────────────────────
import React, { useEffect, useState } from "react";
import { Header } from "../Layout";
import { useLive, formatTime } from "../LiveContext";
import { api } from "../api";
import type { AppSettings, VehicleRecord } from "../types";

type Tab = "manual" | "data" | "settings";
type Category = "Student" | "Faculty" | "Staff" | "Visitor";

interface VehicleForm {
  plate: string;
  name: string;
  category: Category;
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="metric card">
      <small>{label}</small>
      <strong>{value}</strong>
    </article>
  );
}

function LoginGate({ onLogin }: { onLogin: () => void }) {
  return (
    <>
      <Header title="Administrator login" note="Secure access to parking operations" />
      <form
        className="login card"
        onSubmit={(e) => {
          e.preventDefault();
          sessionStorage.setItem("parking-admin", "true");
          onLogin();
        }}
      >
        <h2>Sign in</h2>
        <label>
          Email
          <input type="email" required placeholder="admin@campus.edu" />
        </label>
        <label>
          Password
          <input type="password" required placeholder="••••••••" />
        </label>
        <button className="primary">Sign in</button>
        <small>Demo login accepts any non-empty credentials.</small>
      </form>
    </>
  );
}

export function Admin() {
  const { result, history } = useLive();
  const [logged, setLogged] = useState(
    sessionStorage.getItem("parking-admin") === "true",
  );
  const [tab, setTab] = useState<Tab>("manual");
  const [form, setForm] = useState<VehicleForm>({ plate: "", name: "", category: "Student" });
  const [settings, setSettings] = useState<AppSettings>({
    campus_name: "Smart Campus",
    total_slots: 50,
  });
  const [records, setRecords] = useState<VehicleRecord[]>([]);
  const [notice, setNotice] = useState("");

  const loadAdminData = () =>
    Promise.all([api<VehicleRecord[]>("/vehicles"), api<AppSettings>("/settings")])
      .then(([vehicles, saved]) => {
        setRecords(vehicles);
        setSettings(saved);
      })
      .catch(() => setNotice("Unable to load admin data."));

  useEffect(() => {
    if (logged) loadAdminData();
  }, [logged]);

  if (!logged) return <LoginGate onLogin={() => setLogged(true)} />;

  const manualCheck = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/results/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate: form.plate }),
      });
      setNotice("Manual result sent to every live display.");
    } catch (err) {
      setNotice((err as Error).message);
    }
  };

  const addVehicle = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = { plate: form.plate, owner_name: form.name, category: form.category };
      const exists = records.some((r) => r.plate === form.plate);
      await api(exists ? `/vehicles/${form.plate}` : "/vehicles", {
        method: exists ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exists ? { owner_name: form.name, category: form.category } : payload),
      });
      setForm({ plate: "", name: "", category: "Student" });
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

  const totalSlots = result.totalSlots || settings.total_slots;

  return (
    <>
      <Header title="Admin page" note="Manage vehicle access and system settings." />

      <section className="metrics">
        <Metric label="Total bays" value={totalSlots} />
        <Metric label="Occupied" value={result.occupied || 0} />
        <Metric label="Available" value={totalSlots - (result.occupied || 0)} />
        <Metric label="Latest space" value={result.slot || "—"} />
      </section>

      <section className="admin-tabs card">
        <div className="tab-list">
          {(["manual", "data", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t === "manual" ? "Manual check" : t === "data" ? "Add data" : "Account settings"}
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
          </div>
        )}

        {tab === "data" && (
          <div className="admin-content">
            <h2>Add or edit vehicle record</h2>
            <p>Saving an existing plate updates its record in SQLite.</p>
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
              <button className="primary">Save vehicle record</button>
            </form>

            <div className="records-list">
              {records.map((rec) => (
                <div key={rec.plate}>
                  <span className="mono">{rec.plate}</span>
                  <span>{rec.owner_name} · {rec.category}</span>
                  <button
                    type="button"
                    onClick={() =>
                      setForm({ plate: rec.plate, name: rec.owner_name, category: rec.category as Category })
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
                onClick={() => {
                  sessionStorage.removeItem("parking-admin");
                  setLogged(false);
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
                <td className="mono">{row.plate}</td>
                <td>{row.studentName}</td>
                <td>
                  <b>{row.slot}</b> · {row.direction}
                </td>
                <td>
                  <span className="tag">Granted</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
