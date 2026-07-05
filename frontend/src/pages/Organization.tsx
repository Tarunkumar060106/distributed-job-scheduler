import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useWorkspace } from "../App";
import { Badge, PageHead } from "../ui";

const ROLE_COLORS: Record<string, string> = {
  OWNER: "RUNNING", ADMIN: "SCHEDULED", MEMBER: "COMPLETED", VIEWER: "CANCELLED",
};

export default function Organization() {
  const ws = useWorkspace();
  const org = ws.org;
  const [members, setMembers] = useState<any[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("MEMBER");
  const [newOrgName, setNewOrgName] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    if (!org) return;
    setMembers(await api(`/orgs/${org.id}/members`));
  }, [org?.id]);

  useEffect(() => { refresh().catch(console.error); }, [refresh]);

  if (!org) return <PageHead title="Organization" sub="Loading…" />;

  const canManage = org.my_role === "OWNER" || org.my_role === "ADMIN";

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setNotice("");
    try {
      await api(`/orgs/${org!.id}/members`, {
        method: "POST", body: { email: inviteEmail, role: inviteRole },
      });
      setNotice(`${inviteEmail} added as ${inviteRole}.`);
      setInviteEmail("");
      refresh();
      ws.refresh();
    } catch (err: any) { setError(err.message); }
  }

  async function createOrg(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setNotice("");
    try {
      await api("/orgs", { method: "POST", body: { name: newOrgName } });
      setNotice(`Organization “${newOrgName}” created — switch to it in the sidebar.`);
      setNewOrgName("");
      ws.refresh();
    } catch (err: any) { setError(err.message); }
  }

  async function createProject(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setNotice("");
    try {
      await api(`/orgs/${org!.id}/projects`, {
        method: "POST", body: { name: newProjectName },
      });
      setNotice(`Project “${newProjectName}” created.`);
      setNewProjectName("");
      ws.refresh();
    } catch (err: any) { setError(err.message); }
  }

  return (
    <div>
      <PageHead
        title={org.name}
        sub={`${org.member_count} member${org.member_count === 1 ? "" : "s"} · ${org.project_count} project${org.project_count === 1 ? "" : "s"} · your role: ${org.my_role}`}
        right={<Badge status={ROLE_COLORS[org.my_role]} label={org.my_role} />}
      />

      {(error || notice) && (
        <div className="panel" style={{ padding: "12px 24px" }}>
          {error && <span className="error" style={{ marginTop: 0 }}>{error}</span>}
          {notice && <span className="muted">{notice}</span>}
        </div>
      )}

      <div className="panel">
        <h3>Members</h3>
        <table>
          <thead>
            <tr><th>Name</th><th>Email</th><th>Role</th></tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}>
                <td>{m.name}</td>
                <td className="muted">{m.email}</td>
                <td><Badge status={ROLE_COLORS[m.role]} label={m.role} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {canManage && (
          <form className="row" style={{ marginTop: 16 }} onSubmit={invite}>
            <input type="email" placeholder="teammate@company.com" value={inviteEmail}
                   onChange={(e) => setInviteEmail(e.target.value)} required
                   style={{ minWidth: 240 }} />
            <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
              <option>ADMIN</option>
              <option>MEMBER</option>
              <option>VIEWER</option>
            </select>
            <button type="submit">Add member</button>
            <span className="muted">The user must already have an account.</span>
          </form>
        )}
      </div>

      <div className="panel">
        <h3>Projects</h3>
        <table>
          <thead><tr><th>Name</th><th></th></tr></thead>
          <tbody>
            {ws.projects.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="muted">{p.id === ws.projectId ? "current" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {canManage && (
          <form className="row" style={{ marginTop: 16 }} onSubmit={createProject}>
            <input placeholder="New project name" value={newProjectName}
                   onChange={(e) => setNewProjectName(e.target.value)} required />
            <button type="submit">Create project</button>
          </form>
        )}
      </div>

      <div className="panel">
        <h3>New organization</h3>
        <p className="muted" style={{ marginBottom: 12 }}>
          Organizations are fully isolated tenants: separate members, projects,
          queues, and jobs. You become the OWNER of any organization you create.
        </p>
        <form className="row" onSubmit={createOrg}>
          <input placeholder="Organization name" value={newOrgName}
                 onChange={(e) => setNewOrgName(e.target.value)} required />
          <button type="submit">Create organization</button>
        </form>
      </div>
    </div>
  );
}
