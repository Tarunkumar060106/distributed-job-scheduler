import { useEffect, useState } from "react";
import { STATUS_COLORS, overviewSocket } from "../api";

interface Snapshot {
  job_counts: Record<string, number>;
  worker_counts: Record<string, number>;
  throughput: { minute: string; completed: number }[];
}

const CARD_ORDER = ["QUEUED", "SCHEDULED", "RUNNING", "COMPLETED", "DEAD_LETTER"];

export default function Overview() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    // Live updates over WebSocket, pushed by the API every 2 seconds.
    const ws = overviewSocket((data) => { setSnap(data); setLive(true); });
    ws.onclose = () => setLive(false);
    return () => ws.close();
  }, []);

  if (!snap) return <h2>Loading overview…</h2>;

  const bars = snap.throughput;
  const max = Math.max(1, ...bars.map((b) => b.completed));

  return (
    <div>
      <h2>
        System Overview{" "}
        <span className="muted">{live ? "● live (WebSocket)" : "○ disconnected"}</span>
      </h2>
      <div className="cards">
        {CARD_ORDER.map((status) => (
          <div className="card" key={status}>
            <div className="label">{status.replace("_", " ")}</div>
            <div className="value" style={{ color: STATUS_COLORS[status] }}>
              {snap.job_counts[status] ?? 0}
            </div>
          </div>
        ))}
      </div>
      <div className="panel">
        <h3>Completed jobs per minute (last 30 min)</h3>
        {bars.length === 0 ? (
          <div className="muted">No completions yet — create some jobs.</div>
        ) : (
          <div className="chart-bars">
            {bars.map((bar) => (
              <div key={bar.minute} className="bar" title={`${bar.minute}: ${bar.completed}`}
                   style={{ height: `${(bar.completed / max) * 100}%` }} />
            ))}
          </div>
        )}
      </div>
      <div className="cards">
        {Object.entries(snap.worker_counts).map(([status, count]) => (
          <div className="card" key={status}>
            <div className="label">Workers {status}</div>
            <div className="value" style={{ color: STATUS_COLORS[status] }}>{count}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
