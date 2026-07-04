import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Queues from "./pages/Queues";
import Workers from "./pages/Workers";

export interface ProjectCtx {
  projectId: string | null;
  orgId: string | null;
}
const ProjectContext = createContext<ProjectCtx>({ projectId: null, orgId: null });
export const useProject = () => useContext(ProjectContext);

function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">
          Meridian
          <small>Job Scheduler</small>
        </div>
        <div className="nav-label">Monitor</div>
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/workers">Workers</NavLink>
        <div className="nav-label">Manage</div>
        <NavLink to="/queues">Queues</NavLink>
        <NavLink to="/jobs">Jobs</NavLink>
        <div className="spacer" />
        <a href="#" className="signout"
           onClick={(e) => { e.preventDefault(); setToken(null); navigate("/login"); }}>
          Sign out
        </a>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}

export default function App() {
  const [ctx, setCtx] = useState<ProjectCtx>({ projectId: null, orgId: null });
  const authed = !!getToken();

  useEffect(() => {
    if (!authed) return;
    (async () => {
      // Default workspace: first org, first project (created if missing).
      const orgs = await api("/orgs");
      const org = orgs[0];
      let projects = await api(`/orgs/${org.id}/projects`);
      if (projects.length === 0) {
        projects = [await api(`/orgs/${org.id}/projects`, {
          method: "POST", body: { name: "default", description: "Default project" },
        })];
      }
      setCtx({ orgId: org.id, projectId: projects[0].id });
    })().catch(console.error);
  }, [authed]);

  if (!authed) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    );
  }

  return (
    <ProjectContext.Provider value={ctx}>
      <Layout>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/queues" element={<Queues />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
          <Route path="/workers" element={<Workers />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </Layout>
    </ProjectContext.Provider>
  );
}
