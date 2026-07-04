import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, STATUS_COLORS } from "../api";
import { useProject } from "../App";

const STATUSES = ["", "QUEUED", "SCHEDULED", "RUNNING", "COMPLETED", "FAILED",
  "DEAD_LETTER", "CANCELLED"];
const TASKS = ["echo", "sleep", "send_email", "flaky", "always_fail"];

export default function Jobs() {
  const { projectId } = useProject();
  const [queues, setQueues] = useState<any[]>([]);
  const [queueId, setQueueId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<any>(null);
  const [newTask, setNewTask] = useState("echo");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId) return;
    api(`/projects/${projectId}/queues`).then((qs) => {
      setQueues(qs);
      if (qs.length && !queueId) setQueueId(qs[0].id);
    });
  }, [projectId]);

  const refresh = useCallback(async () => {
    if (!queueId) return;
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (status) params.set("status", status);
    setData(await api(`/queues/${queueId}/jobs?${params}`));
  }, [queueId, status, page]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function createJob(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const payload = newTask === "flaky" ? { failure_rate: 0.5 }
        : newTask === "sleep" ? { seconds: 2 }
        : newTask === "send_email" ? { to: "demo@example.com" } : {};
      await api(`/queues/${queueId}/jobs`, {
        method: "POST", body: { task: newTask, payload },
      });
      refresh();
    } catch (err: any) { setError(err.message); }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div>
      <h2>Job Explorer</h2>
      <div className="panel">
        <div className="row">
          <select value={queueId} onChange={(e) => { setQueueId(e.target.value); setPage(1); }}>
            {queues.map((q) => <option key={q.id} value={q.id}>{q.name}</option>)}
          </select>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
          </select>
          <span className="spacer" style={{ flex: 1 }} />
          <form className="row" onSubmit={createJob}>
            <select value={newTask} onChange={(e) => setNewTask(e.target.value)}>
              {TASKS.map((t) => <option key={t}>{t}</option>)}
            </select>
            <button type="submit" disabled={!queueId}>Enqueue demo job</button>
          </form>
        </div>
        {error && <div className="error">{error}</div>}
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr><th>Task</th><th>Status</th><th>Type</th><th>Priority</th>
                <th>Attempt</th><th>Created</th><th>Error</th></tr>
          </thead>
          <tbody>
            {data?.items.map((job: any) => (
              <tr key={job.id}>
                <td><Link to={`/jobs/${job.id}`} style={{ color: "#60a5fa" }}>{job.task}</Link></td>
                <td><span className="badge" style={{ background: STATUS_COLORS[job.status] }}>
                  {job.status}</span></td>
                <td>{job.type}</td>
                <td>{job.priority}</td>
                <td>{job.attempt}/{job.max_attempts}</td>
                <td className="muted">{new Date(job.created_at).toLocaleTimeString()}</td>
                <td className="muted" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {job.last_error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
          <span className="muted">page {page} / {totalPages} · {data?.total ?? 0} jobs</span>
          <button className="secondary" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>
    </div>
  );
}
