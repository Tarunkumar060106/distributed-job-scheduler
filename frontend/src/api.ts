const BASE = "/api";

export function getToken(): string | null {
  return localStorage.getItem("token");
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem("token", token);
  else localStorage.removeItem("token");
}

export async function api<T = any>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) {
    setToken(null);
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
}

export function overviewSocket(onMessage: (data: any) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${window.location.host}${BASE}/ws/overview?token=${getToken()}`,
  );
  ws.onmessage = (event) => onMessage(JSON.parse(event.data));
  return ws;
}

export const STATUS_COLORS: Record<string, string> = {
  QUEUED: "#f59e0b",
  SCHEDULED: "#8b5cf6",
  CLAIMED: "#06b6d4",
  RUNNING: "#3b82f6",
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  DEAD_LETTER: "#991b1b",
  CANCELLED: "#6b7280",
  ONLINE: "#22c55e",
  DRAINING: "#f59e0b",
  OFFLINE: "#6b7280",
  DEAD: "#ef4444",
};
