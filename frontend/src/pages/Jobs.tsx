import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useProject } from "../App";
import { Badge, PageHead } from "../ui";

const STATUSES = ["", "QUEUED", "SCHEDULED", "RUNNING", "COMPLETED", "FAILED",
  "DEAD_LETTER", "CANCELLED"];

interface TaskEntry {
  name: string;
  description: string;
  idempotent: boolean;
  example: Record<string, unknown>;
}

export default function Jobs() {
  const { projectId } = useProject();
  const [queues, setQueues] = useState<any[]>([]);
  const [queueId, setQueueId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<any>(null);
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [taskName, setTaskName] = useState("");
  const [payloadText, setPayloadText] = useState("{}");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId) return;
    api(`/projects/${projectId}/queues`).then((qs) => {
      setQueues(qs);
      if (qs.length && !queueId) setQueueId(qs[0].id);
    });
    // Task catalog comes from the worker fleet's registered handler packs.
    api("/tasks").then((entries: TaskEntry[]) => {
      setTasks(entries);
      if (entries.length && !taskName) {
        setTaskName(entries[0].name);
        setPayloadText(JSON.stringify(entries[0].example, null, 2));
      }
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

  const selectedTask = tasks.find((t) => t.name === taskName);

  function pickTask(name: string) {
    setTaskName(name);
    const entry = tasks.find((t) => t.name === name);
    setPayloadText(JSON.stringify(entry?.example ?? {}, null, 2));
  }

  async function createJob(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    let payload: unknown;
    try {
      payload = JSON.parse(payloadText || "{}");
    } catch {
      setError("Payload is not valid JSON.");
      return;
    }
    try {
      await api(`/queues/${queueId}/jobs`, {
        method: "POST", body: { task: taskName, payload },
      });
      refresh();
    } catch (err: any) { setError(err.message); }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div>
      <PageHead title="Jobs"
                sub="Inspect, filter, and enqueue jobs across your queues." />

      <div className="panel">
        <h3>Enqueue a job</h3>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 220 }}>
            <select value={queueId} onChange={(e) => { setQueueId(e.target.value); setPage(1); }}>
              {queues.map((q) => <option key={q.id} value={q.id}>queue: {q.name}</option>)}
            </select>
            <select value={taskName} onChange={(e) => pickTask(e.target.value)}>
              {tasks.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
            </select>
            {selectedTask && (
              <span className="muted">
                {selectedTask.description}
                {!selectedTask.idempotent && " · not idempotent"}
              </span>
            )}
          </div>
          <form onSubmit={createJob}
                style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
            <textarea
              className="payload-editor"
              rows={5}
              value={payloadText}
              onChange={(e) => setPayloadText(e.target.value)}
              spellCheck={false}
            />
            <div className="row">
              <button type="submit" disabled={!queueId || !taskName}>Enqueue job</button>
              {error && <span className="error" style={{ marginTop: 0 }}>{error}</span>}
            </div>
          </form>
        </div>
      </div>

      <div className="panel">
        <div className="row" style={{ marginBottom: 12 }}>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace("_", " ") : "All statuses"}</option>)}
          </select>
        </div>
        <table>
          <thead>
            <tr><th>Task</th><th>Status</th><th>Type</th><th>Priority</th>
                <th>Attempt</th><th>Created</th><th>Error</th></tr>
          </thead>
          <tbody>
            {data?.items.map((job: any) => (
              <tr key={job.id}>
                <td><Link to={`/jobs/${job.id}`}>{job.task}</Link></td>
                <td><Badge status={job.status} /></td>
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
        {data && data.total === 0 &&
          <div className="empty">No jobs match this filter yet.</div>}
        <div className="row" style={{ marginTop: 14 }}>
          <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
          <span className="muted">page {page} of {totalPages} · {data?.total ?? 0} jobs</span>
          <button className="secondary" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>
    </div>
  );
}
