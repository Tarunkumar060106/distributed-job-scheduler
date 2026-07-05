import { useState } from "react";
import { setToken } from "../api";

const DEMO_ACCOUNTS = [
  { role: "OWNER", email: "owner@demo.io", blurb: "Full control" },
  { role: "ADMIN", email: "admin@demo.io", blurb: "Manage queues & members" },
  { role: "MEMBER", email: "member@demo.io", blurb: "Run & retry jobs" },
  { role: "VIEWER", email: "viewer@demo.io", blurb: "Read-only" },
];

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  async function login(body: object, endpoint: string) {
    setError("");
    const res = await fetch(`/api/auth/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      setError(typeof data.detail === "string" ? data.detail : "Validation failed");
      return;
    }
    // A demo login should land in the shared demo workspace, not whatever
    // org a previous session had selected.
    localStorage.removeItem("orgId");
    localStorage.removeItem("projectId");
    setToken(data.access_token);
    window.location.href = "/";
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await login(mode === "login" ? { email, password }
                                 : { email, password, name }, mode);
  }

  async function demoLogin(demoEmail: string) {
    setBusy(demoEmail);
    try {
      await login({ email: demoEmail, password: "demo1234" }, "login");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-box" onSubmit={submit}>
        <div className="brand">Meridian</div>
        <div className="tagline">Distributed job scheduling, done properly.</div>
        {mode === "register" && (
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        )}
        <input type="email" placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password (min 8 chars)" value={password}
               onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        <button type="submit">{mode === "login" ? "Sign in" : "Create account"}</button>
        {error && <div className="error">{error}</div>}
        <a href="#" className="switch" onClick={(e) => {
          e.preventDefault();
          setMode(mode === "login" ? "register" : "login");
        }}>
          {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
        </a>

        <div className="demo-divider"><span>or explore with a demo account</span></div>
        <div className="demo-grid">
          {DEMO_ACCOUNTS.map((account) => (
            <button key={account.email} type="button" className="secondary demo-btn"
                    disabled={busy !== ""}
                    onClick={() => demoLogin(account.email)}>
              <span className="demo-role">
                {busy === account.email ? "Signing in…" : account.role}
              </span>
              <span className="demo-blurb">{account.blurb}</span>
            </button>
          ))}
        </div>
        <div className="switch" style={{ marginTop: 4 }}>
          All demo accounts share one organization — switch between them to
          compare permissions.
        </div>
      </form>
    </div>
  );
}
