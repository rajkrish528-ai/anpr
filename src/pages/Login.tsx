import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Header } from "../Layout";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    
    try {
      const res = await api<{ token: string; admin_id: number }>("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      
      localStorage.setItem("parking-admin-token", res.token);
      navigate("/admin");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrapper">
      <div className="login-container">
        <Header title="Administrator Access" note="Authenticate to manage the smart parking system." />
        <form className="login card" onSubmit={handleLogin}>
          <h2>Sign in to Parkwise</h2>
          
          {error && <div className="setup-notice err" style={{ marginBottom: '1rem' }}>{error}</div>}
          
          <label>
            Email
            <input 
              type="email" 
              required 
              placeholder="admin@campus.edu"
              value={email}
              onChange={e => setEmail(e.target.value)}
              disabled={loading}
            />
          </label>
          <label>
            Password
            <input 
              type="password" 
              required 
              placeholder="••••••••"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
            />
          </label>
          <button className="primary login-btn" disabled={loading}>
            {loading ? "Authenticating..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
