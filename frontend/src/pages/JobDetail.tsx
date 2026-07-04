import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, STATUS_COLORS } from "../api";

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

  if (!job) return <h2>Loading…</h2>;

  return (
    <div>
      <h2>
        {job.task}{" "}
        <span className="badge" style={{ background: STATUS_COLORS[job.status] }}>{job.status}</span>
      </h2>
      <div className="panel">
        <div className="row" style={{ marginBottom: 10 }}>
          <button onClick={() => act("retry")}>Retry</button>
          <button className="danger" onClick={() => act("cancel")}>Cancel</button>
          {error && <span className="error">{error}</span>}
        </div>
        <table>
          <tbody>
            <tr><th>ID</th><td>{job.id}</td></tr>
            <tr><th>Type</th><td>{job.type}</td></tr>
            <tr><th>Payload</th><td><code>{JSON.stringify(job.payload)}</code></td></tr>
            <tr><th>Result</th><td><code>{JSON.stringify(job.result)}</code></td></tr>
            <tr><th>Attempts</th><td>{job.attempt} / {job.max_attempts}</td></tr>
            <tr><th>Run at</th><td>{job.run_at}</td></tr>
            <tr><th>Worker</th><td>{job.worker_id ?? "–"}</td></tr>
            <tr><th>Last error</th><td className="error">{job.last_error ?? "–"}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h3>Execution history ({job.executions.length} attempt{job.executions.length === 1 ? "" : "s"})</h3>
        <table>
          <thead>
            <tr><th>#</th><th>Status</th><th>Worker</th><th>Started</th><th>Duration</th><th>Error</th></tr>
          </thead>
          <tbody>
            {job.executions.map((ex: any) => (
              <tr key={ex.id}>
                <td>{ex.attempt}</td>
                <td><span className="badge" style={{
                  background: ex.status === "SUCCESS" ? "#22c55e"
                    : ex.status === "RUNNING" ? "#3b82f6" : "#ef4444" }}>{ex.status}</span></td>
                <td className="muted">{ex.worker_id?.slice(0, 8) ?? "–"}</td>
                <td className="muted">{new Date(ex.started_at).toLocaleTimeString()}</td>
                <td>{ex.duration_ms ? `${ex.duration_ms.toFixed(0)}ms` : "–"}</td>
                <td className="muted">{ex.error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h3>Logs</h3>
        <div className="logs">
          {logs.map((line) => (
            <div key={line.id}>
              <span className="muted">{new Date(line.created_at).toLocaleTimeString()} </span>
              <span style={{ color: line.level === "ERROR" ? "#f87171"
                : line.level === "WARN" ? "#fbbf24" : "#94a3b8" }}>{line.level}</span>{" "}
              {line.message}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
