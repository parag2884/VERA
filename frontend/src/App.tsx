import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { BRAND } from "./brand";
import { WorkspaceProvider, useWorkspace } from "./state";
import Home from "./pages/Home";
import Connect from "./pages/Connect";
import Ask from "./pages/Ask";
import KnowledgeMap from "./pages/KnowledgeMap";
import Insights from "./pages/Insights";
import AgentBuilder from "./pages/AgentBuilder";
import Deploy from "./pages/Deploy";
import Embed from "./pages/Embed";
import Fleet from "./pages/Fleet";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/fleet", label: "Fleet", end: false },
  { to: "/agent", label: "Agents", end: false },
  { to: "/deploy", label: "Deploy", end: false },
  { to: "/connect", label: "Connect", end: false },
  { to: "/ask", label: "Ask", end: false },
  { to: "/map", label: "Maps", end: false },
  { to: "/insights", label: "Insights", end: false },
];

const TITLES: Record<string, { title: string; sub: string }> = {
  "/": { title: "Studio", sub: "Your agent fleet" },
  "/fleet": { title: "Fleet", sub: "Active · Disable · Delete" },
  "/agent": { title: "Agents", sub: "Identity · voice · publish" },
  "/deploy": { title: "Deploy", sub: "Endpoints · pricing · embeds" },
  "/connect": { title: "Connect", sub: "Feed the active agent’s knowledge" },
  "/ask": { title: "Ask", sub: "Evidence-bound answers" },
  "/map": { title: "Knowledge maps", sub: "One graph per agent" },
  "/insights": { title: "Insights", sub: "Health per agent" },
};

function Shell() {
  const { demoMode, currentAgent, agents, agentId, selectAgent } = useWorkspace();
  const loc = useLocation();
  const meta = TITLES[loc.pathname] || TITLES["/"];

  const askFocus = loc.pathname === "/ask";
  const mapFocus = loc.pathname === "/map";
  const chromeFocus = askFocus || mapFocus;

  return (
    <div
      className={`app-shell${askFocus ? " app-ask-focus" : ""}${mapFocus ? " app-map-focus" : ""}`}
    >
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand">
            VER<span>A</span>
          </div>
          <div className="brand-tag">{BRAND.tagline}</div>
        </div>

        <div className="sidebar-nav-block">
          <div className="nav-label">Studio</div>
          <nav className="nav">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="sidebar-fleet">
          <div className="sidebar-fleet-head">
            <div className="nav-label">Active agent</div>
            {agents.length > 0 && (
              <span className="sidebar-fleet-count">{agents.length}</span>
            )}
          </div>
          {currentAgent ? (
            <div className="sidebar-active-card">
              <strong title={currentAgent.name}>{currentAgent.name}</strong>
              <span>
                {currentAgent.counts?.documents ?? 0} docs ·{" "}
                {currentAgent.disabled
                  ? "disabled"
                  : currentAgent.published
                    ? "live"
                    : (currentAgent.counts?.documents ?? 0) > 0
                      ? "ready"
                      : "draft"}
              </span>
            </div>
          ) : (
            <p className="sidebar-fleet-empty">No agent selected</p>
          )}
          {agents.length > 1 && (
            <label className="sidebar-switch">
              <span>Switch</span>
              <select
                value={agentId || ""}
                onChange={(e) => {
                  if (e.target.value) void selectAgent(e.target.value);
                }}
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {a.published ? " · live" : a.disabled ? " · off" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <NavLink className="sidebar-fleet-link" to="/fleet">
            {agents.length > 1 ? "Manage all agents" : "Open fleet"}
          </NavLink>
        </div>

        <div className="sidebar-foot">
          <strong>Trust invariant</strong>
          No evidence-bearing edge = no answer-bearing edge.
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <div className="topbar-title">{meta.title}</div>
            <div className="topbar-sub">{meta.sub}</div>
          </div>

          <div className="topbar-center">
            {!chromeFocus && (
              <>
                <label className="agent-switch">
                  <span>Working on</span>
                  <select
                    value={agentId || ""}
                    onChange={(e) => {
                      if (e.target.value) void selectAgent(e.target.value);
                    }}
                  >
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                        {a.published ? " · live" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {askFocus && (
              <span className="topbar-ask-hint muted">Select the agent inside the chat</span>
            )}
            {mapFocus && (
              <span className="topbar-ask-hint muted">Select the agent on the map</span>
            )}
          </div>

          <div className="topbar-right">
            {demoMode ? (
              <span className="pill warn">Demo mode</span>
            ) : (
              <span className="pill live">Azure live</span>
            )}
            <span className="pill">Graph-primary</span>
          </div>
        </header>

        <main className="main">
          {demoMode && (
            <div className="demo-banner">
              Demo mode: Mock provider active — answers are labeled, never silent failover.
            </div>
          )}
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/fleet" element={<Fleet />} />
            <Route path="/agent" element={<AgentBuilder />} />
            <Route path="/deploy" element={<Deploy />} />
            <Route path="/connect" element={<Connect />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="/map" element={<KnowledgeMap />} />
            <Route path="/insights" element={<Insights />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <WorkspaceProvider>
      <Routes>
        <Route path="/embed/:embedKey" element={<Embed />} />
        <Route path="/*" element={<Shell />} />
      </Routes>
    </WorkspaceProvider>
  );
}
