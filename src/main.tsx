// ─────────────────────────────────────────────────────────────
// Application entry point
// ─────────────────────────────────────────────────────────────
import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { LiveProvider } from "./LiveContext";
import { Shell } from "./Layout";
import "./styles.css";

import { Dashboard }     from "./pages/Dashboard";
import { SystemSetup }   from "./pages/SystemSetup";
import { Admin }         from "./pages/Admin";
import { ResultDisplay } from "./pages/ResultDisplay";
import { CameraMonitor } from "./pages/CameraMonitor";
import { Login }         from "./pages/Login";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem("parking-admin-token");
  const { pathname } = useLocation();
  
  if (!token) {
    return <Navigate to="/login" replace state={{ from: pathname }} />;
  }
  return <>{children}</>;
}

function AppRoutes() {
  const { pathname } = useLocation();

  // Full-screen pages rendered without the shell sidebar
  if (pathname === "/gate-camera-preview")
    return <CameraMonitor source="gate" label="CAM-GATE-01" />;
  if (pathname === "/parking-camera-preview")
    return <CameraMonitor source="parking" label="CAM-PARKING-01" />;
  if (pathname === "/result")
    return <ResultDisplay />;

  return (
    <Shell>
      <Routes>
        <Route path="/"      element={<Dashboard />} />
        <Route path="/login" element={<Login />} />
        <Route path="/setup" element={<ProtectedRoute><SystemSetup /></ProtectedRoute>} />
        <Route path="/admin" element={<ProtectedRoute><Admin /></ProtectedRoute>} />
        <Route path="*"      element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

function App() {
  return (
    <LiveProvider>
      <AppRoutes />
    </LiveProvider>
  );
}

const root = document.getElementById("root")!;
createRoot(root).render(
  <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <App />
  </BrowserRouter>,
);
