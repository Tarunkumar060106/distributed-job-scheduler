import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, PageHead } from "../ui";

export default function JobDetail() {
  const { jobId } = useParams();
  const [job, setJob] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setJob(await api(`/jobs/${jobId}`));
    setLogs(await api(`/jobs/${jobId}/logs`));
  }, [jobId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function act(action: "retry" | "cancel") {
    setError("");
    try {
      await api(`/jobs/${jobId}/${action}`, { method: "POST" });
      refresh();
    } catch (err: any) { setError(err.message); }
  }

  if (!job) return <PageHead title="Job" sub="Loading…" />;

  return (
    <div>
      <PageHead
        title={job.task}
        sub={`Job ${job.id}`}
        right={<Badge status={job.status} />}
      />
      <div className="panel">
        <div className="row" style={{ marginBottom: 14 }}>
          <button onClick={() => act("retry")}>Retry</button>
          <button className="danger" onClick={() => act("cancel")}>Cancel</button>
          {error && <span className="error" style={{ marginTop: 0 }}>{error}</span>}
        </div>
        <table className="kv">
          <tbody>
            <tr><th>Type</th><td>{job.type}</td></tr>
            <tr><th>Payload</th><td><code>{JSON.stringify(job.payload)}</code></td></tr>
            <tr><th>Result</th><td>{job.result ? <code>{JSON.stringify(job.result)}</code> : <span className="muted">—</span>}</td></tr>
            <tr><th>Attempts</th><td>{job.attempt} of {job.max_attempts}</td></tr>
            <tr><th>Priority</th><td>{job.priority}</td></tr>
            <tr><th>Run at</th><td>{new Date(job.run_at).toLocaleString()}</td></tr>
            <tr><th>Worker</th><td>{job.worker_name ?? <span className="muted">unassigned</span>}</td></tr>
            <tr><th>Last error</th><td>{job.last_error
              ? <span style={{ color: "var(--red)" }}>{job.last_error}</span>
              : <span className="muted">—</span>}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h3>Execution history — {job.executions.length} attempt{job.executions.length === 1 ? "" : "s"}</h3>
        {job.executions.length === 0
          ? <div className="empty">Not executed yet.</div>
          : <table>
              <thead>
                <tr><th>#</th><th>Status</th><th>Worker</th><th>Started</th><th>Duration</th><th>Error</th></tr>
              </thead>
              <tbody>
                {job.executions.map((ex: any) => (
                  <tr key={ex.id}>
                    <td>{ex.attempt}</td>
                    <td><Badge status={ex.status === "SUCCESS" ? "COMPLETED"
                      : ex.status === "RUNNING" ? "RUNNING"
                      : ex.status === "LOST" ? "DEAD" : "FAILED"} label={ex.status} /></td>
                    <td className="muted">{ex.worker_name ?? ex.worker_id?.slice(0, 8) ?? "—"}</td>
                    <td className="muted">{new Date(ex.started_at).toLocaleTimeString()}</td>
                    <td>{ex.duration_ms ? `${ex.duration_ms.toFixed(0)} ms` : "—"}</td>
                    <td className="muted">{ex.error ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
      </div>
      <div className="panel">
        <h3>Logs</h3>
        <div className="logs">
          {logs.length === 0 && <div className="ts">No log lines yet.</div>}
          {logs.map((line) => (
            <div key={line.id}>
              <span className="ts">{new Date(line.created_at).toLocaleTimeString()} </span>
              <span className={`lvl-${line.level}`}>{line.level.padEnd(5)}</span>{" "}
              {line.message}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
