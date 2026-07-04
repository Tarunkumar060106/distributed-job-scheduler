import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useProject } from "../App";
import { Badge, PageHead } from "../ui";

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
      <PageHead title="Workers"
                sub="Fleet status, heartbeats, and the dead letter queue." />
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
                <td><Badge status={w.status} /></td>
                <td>{w.concurrency}</td>
                <td>{w.jobs_processed}</td>
                <td>{w.jobs_failed}</td>
                <td className="muted">{new Date(w.last_heartbeat_at).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {workers.length === 0 && <div className="empty">
          No workers registered — start one with <code>python -m app.worker</code>.</div>}
      </div>

      <PageHead title="Dead letter queue"
                sub="Jobs that exhausted every retry. Requeue restarts them with a clean slate." />
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
                <td style={{ color: "var(--red)" }}>{entry.error}</td>
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
        {dlq.length === 0 && <div className="empty">The dead letter queue is empty.</div>}
      </div>
    </div>
  );
}
