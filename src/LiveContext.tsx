// ─────────────────────────────────────────────────────────────
// LiveContext — global WebSocket connection + result state
// ─────────────────────────────────────────────────────────────
import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useLocation } from "react-router-dom";
import { WS_URL, api, formatTime } from "./api";
import type { ParkingResult, WsMessage } from "./types";

export { formatTime };

// ── initial / demo state ──────────────────────────────────────
const INITIAL: ParkingResult = {
  plate: "BR01N2323",
  studentName: "Aarav Kumar",
  category: "Student",
  slot: "S2",
  direction: "Level 1 · East Wing",
  confidence: 0.94,
  source: "demo",
  timestamp: new Date().toISOString(),
  occupied: 27,
  totalSlots: 50,
};

// ── context shape ─────────────────────────────────────────────
interface LiveContextValue {
  status: "connecting" | "live" | "offline";
  result: ParkingResult;
  history: ParkingResult[];
  frames: Record<string, string>;
  send: (payload: object) => void;
}

const LiveContext = createContext<LiveContextValue | null>(null);

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive must be used inside <LiveProvider>");
  return ctx;
}

// ── socket-path selection ─────────────────────────────────────
function socketPathFor(pathname: string): string {
  if (pathname === "/gate-camera-preview") return "/ws/camera/gate";
  if (pathname === "/parking-camera-preview") return "/ws/camera/parking";
  if (pathname === "/result") return "/ws/results";
  return "/ws";
}

// ── provider ──────────────────────────────────────────────────
export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<LiveContextValue["status"]>("connecting");
  const [result, setResult] = useState<ParkingResult>(INITIAL);
  const [history, setHistory] = useState<ParkingResult[]>([INITIAL]);
  const [frames, setFrames] = useState<Record<string, string>>({});
  const ws = useRef<WebSocket | null>(null);
  const { pathname } = useLocation();

  // ── WebSocket lifecycle ──────────────────────────────────────
  useEffect(() => {
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      const url = new URL(WS_URL);
      url.pathname = socketPathFor(pathname);
      const socket = new WebSocket(url.toString());
      ws.current = socket;

      socket.onopen = () => {
        setStatus("live");
        socket.send(JSON.stringify({ type: "subscribe" }));
      };

      socket.onmessage = ({ data }: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(data) as WsMessage;
          if (msg.type === "camera_frame" && msg.processedImage) {
            setFrames((prev) => ({ ...prev, [msg.source]: msg.processedImage }));
          }
          if (msg.type === "parking_result") {
            const r = msg as unknown as ParkingResult;
            setResult(r);
            setHistory((prev) => [r, ...prev].slice(0, 30));
            if (r.processedImage) {
              setFrames((prev) => ({ ...prev, [r.source]: r.processedImage! }));
            }
          }
        } catch {
          // ignore malformed messages
        }
      };

      socket.onclose = () => {
        setStatus("offline");
        retryTimer = setTimeout(connect, 2_500);
      };
      socket.onerror = () => socket.close();
    }

    connect();
    return () => {
      clearTimeout(retryTimer);
      ws.current?.close();
    };
  }, [pathname]);

  // ── pre-populate history from REST ──────────────────────────
  useEffect(() => {
    api<ParkingResult[]>("/results?limit=30")
      .then((items) => {
        if (items.length) {
          setHistory(items);
          setResult(items[0]);
        }
      })
      .catch(() => {/* server may be starting */});
  }, []);

  const send = (payload: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(payload));
    }
  };

  return (
    <LiveContext.Provider value={{ status, result, history, frames, send }}>
      {children}
    </LiveContext.Provider>
  );
}
