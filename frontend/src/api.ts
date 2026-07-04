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
  QUEUED: "#b45309",
  SCHEDULED: "#6d28d9",
  CLAIMED: "#0e7490",
  RUNNING: "#1e40af",
  COMPLETED: "#15803d",
  FAILED: "#b91c1c",
  DEAD_LETTER: "#7f1d1d",
  CANCELLED: "#57534e",
  ONLINE: "#15803d",
  DRAINING: "#b45309",
  OFFLINE: "#57534e",
  DEAD: "#b91c1c",
};