// ─────────────────────────────────────────────────────────────
// API client helpers
// ─────────────────────────────────────────────────────────────

/**
 * In dev, use relative paths so the Vite proxy forwards to :8000.
 * In production (or with explicit env vars) use the full URL.
 */
export const API_URL: string =
  import.meta.env.VITE_API_URL ?? "/api";

export const WS_URL: string =
  import.meta.env.VITE_WS_URL ?? `ws://${location.host}/ws`;

/** WebSocket base (strips trailing /ws so we can append any path). */
export const WS_BASE: string = WS_URL.replace(/\/ws$/, "");

/** Typed fetch helper — throws on non-2xx with the server's detail message. */
export async function api<T = unknown>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as Record<string, unknown>;
    throw new Error((body["detail"] as string | undefined) ?? "Request failed");
  }
  if (response.status === 204) return null as T;
  return response.json() as Promise<T>;
}

/** Format an ISO timestamp to a short HH:MM:SS string. */
export function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
