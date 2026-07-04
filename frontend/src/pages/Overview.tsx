import { useEffect, useState } from "react";
import { overviewSocket, STATUS_COLORS } from "../api";
import { PageHead } from "../ui";

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
    // Live updates over WebSocket, relayed through the API gateway.
    const ws = overviewSocket((data) => { setSnap(data); setLive(true); });
    ws.onclose = () => setLive(false);
    return () => ws.close();
  }, []);

  if (!snap) {
    return <PageHead title="Overview" sub="Connecting to the live feed…" />;
  }

  const bars = snap.throughput;
  const max = Math.max(1, ...bars.map((b) => b.completed));
  const workersOnline = snap.worker_counts.ONLINE ?? 0;

  return (
    <div>
      <PageHead
        title="Overview"
        sub={`${workersOnline} worker${workersOnline === 1 ? "" : "s"} online`}
        right={
          <span className="live-indicator">
            <span className={`dot ${live ? "on" : "off"}`} />
            {live ? "Live" : "Reconnecting"}
          </span>
        }
      />
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
        <h3>Completed jobs per minute — last 30 minutes</h3>
        {bars.length === 0 ? (
          <div className="empty">No completions in this window yet.</div>
        ) : (
          <div className="chart-bars">
            {bars.map((bar) => (
              <div key={bar.minute} className="bar"
                   title={`${new Date(bar.minute).toLocaleTimeString()} — ${bar.completed} completed`}
                   style={{ height: `${(bar.completed / max) * 100}%` }} />
            ))}
          </div>
        )}
      </div>
      <div className="cards">
        {Object.entries(snap.worker_counts).map(([status, count]) => (
          <div className="card" key={status}>
            <div className="label">Workers · {status}</div>
            <div className="value" style={{ color: STATUS_COLORS[status] }}>{count}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
