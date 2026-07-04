import { useCallback, useEffect, useState } from "react";
import { api, STATUS_COLORS } from "../api";
import { useProject } from "../App";

export default function Workers() {
  const { projectId } = useProject();
  const [workers, setWorkers] = useState<any[]>([]);
  const [dlq, setDlq] = useState<any[]>([]);
  const [queues, setQueues] = useState<any[]>([]);
  const [queueId, setQueueId] = useState("");

  const refresh = useCallback(async () => {
    setWorkers(await api("/workers"));
    if (queueId) setDlq(await api(`/queues/${queueId}/dlq`));
  }, [queueId]);

  useEffect(() => {
    if (!projectId) return;
    api(`/projects/${projectId}/queues`).then((qs) => {
      setQueues(qs);
      if (qs.length && !queueId) setQueueId(qs[0].id);
    });
  }, [projectId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function requeue(entryId: string) {
    await api(`/dlq/${entryId}/requeue`, { method: "POST" });
    refresh();
  }

  return (
    <div>
      <h2>Workers</h2>
      <div className="panel">
        <table>
          <thead>
            <tr><th>Name</th><th>Status</th><th>Concurrency</th><th>Processed</th>
                <th>Failed</th><th>Last heartbeat</th></tr>
          </thead>
          <tbody>
            {workers.map((w) => (
              <tr key={w.id}>
                <td>{w.name}</td>
                <td><span className="badge" style={{ background: STATUS_COLORS[w.status] }}>
                  {w.status}</span></td>
                <td>{w.concurrency}</td>
                <td>{w.jobs_processed}</td>
                <td>{w.jobs_failed}</td>
                <td className="muted">{new Date(w.last_heartbeat_at).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {workers.length === 0 && <div className="muted" style={{ padding: 12 }}>
          No workers registered — start one with <code>python -m app.worker</code>.</div>}
      </div>

      <h2>Dead Letter Queue</h2>
      <div className="panel">
        <div className="row" style={{ marginBottom: 10 }}>
          <select value={queueId} onChange={(e) => setQueueId(e.target.value)}>
            {queues.map((q) => <option key={q.id} value={q.id}>{q.name}</option>)}
          </select>
        </div>
        <table>
          <thead>
            <tr><th>Job</th><th>Error</th><th>Attempts</th><th>Dead since</th><th></th></tr>
          </thead>
          <tbody>
            {dlq.map((entry) => (
              <tr key={entry.id}>
                <td className="muted">{entry.job_id.slice(0, 8)}</td>
                <td className="error">{entry.error}</td>
                <td>{entry.attempts_made}</td>
                <td className="muted">{new Date(entry.created_at).toLocaleTimeString()}</td>
                <td>
                  {entry.requeued_at
                    ? <span className="muted">requeued</span>
                    : <button onClick={() => requeue(entry.id)}>Requeue</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {dlq.length === 0 && <div className="muted" style={{ padding: 12 }}>Dead letter queue is empty. 🎉</div>}
      </div>
    </div>
  );
}
