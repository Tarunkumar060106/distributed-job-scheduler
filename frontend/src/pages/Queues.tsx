import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useProject } from "../App";
import { Badge, PageHead } from "../ui";

export default function Queues() {
  const { projectId } = useProject();
  const [queues, setQueues] = useState<any[]>([]);
  const [stats, setStats] = useState<Record<string, any>>({});
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectId) return;
    const qs = await api(`/projects/${projectId}/queues`);
    setQueues(qs);
    const entries = await Promise.all(
      qs.map(async (q: any) => [q.id, await api(`/queues/${q.id}/stats`)]),
    );
    setStats(Object.fromEntries(entries));
  }, [projectId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function createQueue(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api(`/projects/${projectId}/queues`, {
        method: "POST", body: { name, max_concurrency: 10 },
      });
      setName("");
      refresh();
    } catch (err: any) { setError(err.message); }
  }

  async function togglePause(queue: any) {
    await api(`/queues/${queue.id}/${queue.paused ? "resume" : "pause"}`, { method: "POST" });
    refresh();
  }

  return (
    <div>
      <PageHead title="Queues"
                sub="Per-queue concurrency limits, retry policies, and live statistics." />
      <div className="panel">
        <form className="row" onSubmit={createQueue}>
          <input placeholder="New queue name" value={name}
                 onChange={(e) => setName(e.target.value)} required />
          <button type="submit">Create queue</button>
        </form>
        {error && <div className="error">{error}</div>}
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Name</th><th>State</th><th>Concurrency</th>
              <th>Queued</th><th>Running</th><th>Completed</th><th>DLQ</th>
              <th>Avg ms</th><th>1h throughput</th><th></th>
            </tr>
          </thead>
          <tbody>
            {queues.map((queue) => {
              const s = stats[queue.id];
              return (
                <tr key={queue.id}>
                  <td>{queue.name}</td>
                  <td><Badge status={queue.paused ? "DRAINING" : "ONLINE"}
                             label={queue.paused ? "PAUSED" : "ACTIVE"} /></td>
                  <td>{queue.max_concurrency}</td>
                  <td>{s?.counts.QUEUED ?? "–"}</td>
                  <td>{(s?.counts.RUNNING ?? 0) + (s?.counts.CLAIMED ?? 0)}</td>
                  <td>{s?.counts.COMPLETED ?? "–"}</td>
                  <td>{s?.counts.DEAD_LETTER ?? "–"}</td>
                  <td>{s?.avg_duration_ms?.toFixed(0) ?? "–"}</td>
                  <td>{s?.throughput_last_hour ?? "–"}</td>
                  <td>
                    <button className="secondary" onClick={() => togglePause(queue)}>
                      {queue.paused ? "Resume" : "Pause"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {queues.length === 0 &&
          <div className="empty">No queues yet — create your first one above.</div>}
      </div>
    </div>
  );
}
