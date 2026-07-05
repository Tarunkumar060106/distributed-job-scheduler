import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Organization from "./pages/Organization";
import Overview from "./pages/Overview";
import Queues from "./pages/Queues";
import Workers from "./pages/Workers";

export interface Org {
  id: string; name: string; my_role: string;
  member_count: number; project_count: number;
}
export interface Project { id: string; name: string; }

interface WorkspaceCtx {
  orgs: Org[];
  org: Org | null;
  projects: Project[];
  projectId: string | null;
  selectOrg: (orgId: string) => void;
  selectProject: (projectId: string) => void;
  refresh: () => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceCtx>(null as any);
export const useWorkspace = () => useContext(WorkspaceContext);
// Backwards-compatible hook used by the pages.
export const useProject = () => {
  const ws = useWorkspace();
  return { projectId: ws.projectId, orgId: ws.org?.id ?? null };
};

function Sidebar() {
  const navigate = useNavigate();
  const ws = useWorkspace();
  return (
    <nav className="sidebar">
      <div className="brand">
        Meridian
        <small>Job Scheduler</small>
      </div>

      <div className="nav-label">Workspace</div>
      <div className="workspace-picker">
        <select value={ws.org?.id ?? ""} title="Organization"
                onChange={(e) => ws.selectOrg(e.target.value)}>
          {ws.orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select value={ws.projectId ?? ""} title="Project"
                onChange={(e) => ws.selectProject(e.target.value)}>
          {ws.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
      <NavLink to="/organization">Organization</NavLink>

      <div className="nav-label">Monitor</div>
      <NavLink to="/" end>Overview</NavLink>
      <NavLink to="/workers">Workers</NavLink>

      <div className="nav-label">Manage</div>
      <NavLink to="/queues">Queues</NavLink>
      <NavLink to="/jobs">Jobs</NavLink>

      <div className="spacer" />
      {ws.org && (
        <div className="role-chip">
          Signed in as <strong>{ws.org.my_role}</strong>
        </div>
      )}
      <a href="#" className="signout"
         onClick={(e) => { e.preventDefault(); setToken(null); navigate("/login"); }}>
        Sign out
      </a>
    </nav>
  );
}

export default function App() {
  const authed = !!getToken();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState<string | null>(localStorage.getItem("orgId"));
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(
    localStorage.getItem("projectId"));

  const loadProjects = useCallback(async (targetOrgId: string, keepSelection: boolean) => {
    let list: Project[] = await api(`/orgs/${targetOrgId}/projects`);
    if (list.length === 0) {
      list = [await api(`/orgs/${targetOrgId}/projects`, {
        method: "POST", body: { name: "default", description: "Default project" },
      })];
    }
    setProjects(list);
    const stored = localStorage.getItem("projectId");
    const still = keepSelection && list.some((p) => p.id === stored);
    const chosen = still ? stored! : list[0].id;
    setProjectId(chosen);
    localStorage.setItem("projectId", chosen);
  }, []);

  const refresh = useCallback(async () => {
    const found: Org[] = await api("/orgs");
    setOrgs(found);
    const stored = localStorage.getItem("orgId");
    const chosen = found.find((o) => o.id === stored) ?? found[0];
    if (chosen) {
      setOrgId(chosen.id);
      localStorage.setItem("orgId", chosen.id);
      await loadProjects(chosen.id, true);
    }
  }, [loadProjects]);

  useEffect(() => {
    if (authed) refresh().catch(console.error);
  }, [authed, refresh]);

  if (!authed) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    );
  }

  const ctx: WorkspaceCtx = {
    orgs,
    org: orgs.find((o) => o.id === orgId) ?? null,
    projects,
    projectId,
    selectOrg: (id) => {
      setOrgId(id);
      localStorage.setItem("orgId", id);
      loadProjects(id, false).catch(console.error);
    },
    selectProject: (id) => {
      setProjectId(id);
      localStorage.setItem("projectId", id);
    },
    refresh,
  };

  return (
    <WorkspaceContext.Provider value={ctx}>
      <div className="layout">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/organization" element={<Organization />} />
            <Route path="/queues" element={<Queues />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:jobId" element={<JobDetail />} />
            <Route path="/workers" element={<Workers />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </WorkspaceContext.Provider>
  );
}
