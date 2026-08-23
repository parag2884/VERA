import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { BRAND } from "./brand";
import { WorkspaceProvider, useWorkspace } from "./state";
import Home from "./pages/Home";
import Connect from "./pages/Connect";
import Ask from "./pages/Ask";
import KnowledgeMap from "./pages/KnowledgeMap";
import Insights from "./pages/Insights";
import TrustForgePage from "./pages/TrustForge";
import AgentBuilder from "./pages/AgentBuilder";
import Deploy from "./pages/Deploy";
import Embed from "./pages/Embed";
import Fleet from "./pages/Fleet";

const NAV: Array<{ to: string; label: string; end?: boolean }> = [
  { to: "/insights", label: "Operate" },
  { to: "/ask", label: "Ask" },
  { to: "/connect", label: "Connect" },
  { to: "/fleet", label: "Fleet" },
  { to: "/agent", label: "Agents" },
  { to: "/deploy", label: "Deploy" },
  { to: "/trust-forge", label: "Evaluate" },
  { to: "/map", label: "Maps" },
];

const TITLES: Record<string, { title: string; sub: string }> = {
  "/": { title: "Studio", sub: "Operate the fleet — not the graph" },
  "/fleet": { title: "Fleet", sub: "Agents in this studio" },
  "/agent": { title: "Agents", sub: "Identity · voice · publish" },
  "/deploy": { title: "Deploy", sub: "Endpoints · embeds" },
  "/connect": { title: "Connect", sub: "Add knowledge (governed ingest)" },
  "/ask": { title: "Ask", sub: "Evidence-bound answers" },
  "/map": { title: "Maps", sub: "Engineering view of the graph" },
  "/trust-forge": { title: "Evaluate", sub: "Golden-suite proof" },
  "/insights": { title: "Operate", sub: "Health · actions · this week" },
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
          <nav className="nav">
            <NavLink to="/" end>
              <span>Home</span>
            </NavLink>
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
                    : (currentAgent.counts?.documents ?? 0) > 0 ||
                        (currentAgent.counts?.nodes ?? 0) > 0
                      ? "ready"
                      : "draft"}
              </span>
            </div>
          ) : (
            <p className="sidebar-fleet-empty">No agent selected</p>
          )}
          {currentAgent && !currentAgent.published && !currentAgent.disabled && (
            <NavLink className="sidebar-fleet-link" to="/agent">
              Publish this agent
            </NavLink>
          )}
          {currentAgent?.published && (
            <NavLink className="sidebar-fleet-link" to="/deploy">
              Live · manage publish
            </NavLink>
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
            <Route path="/trust-forge" element={<TrustForgePage />} />
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
