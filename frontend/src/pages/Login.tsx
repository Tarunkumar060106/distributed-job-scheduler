import { useState } from "react";
import { setToken } from "../api";

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const body = mode === "login" ? { email, password } : { email, password, name };
    const res = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      setError(typeof data.detail === "string" ? data.detail : "Validation failed");
      return;
    }
    setToken(data.access_token);
    window.location.href = "/";
  }

  return (
    <div className="auth-wrap">
      <form className="auth-box" onSubmit={submit}>
        <h1>⚡ Job Scheduler</h1>
        {mode === "register" && (
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        )}
        <input type="email" placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password (min 8 chars)" value={password}
               onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        <button type="submit">{mode === "login" ? "Sign in" : "Create account"}</button>
        {error && <div className="error">{error}</div>}
        <a href="#" className="muted" onClick={(e) => {
          e.preventDefault();
          setMode(mode === "login" ? "register" : "login");
        }}>
          {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
        </a>
      </form>
    </div>
  );
}
