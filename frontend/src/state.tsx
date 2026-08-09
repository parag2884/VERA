import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  AgentSettings,
  DEFAULT_AGENT_SETTINGS,
  loadAgentSettings,
  saveAgentSettings,
} from "./agentSettings";
import { api, type Agent } from "./api/client";
import { defaultSamplesForAgent } from "./sampleQuestions";

type Ctx = {
  workspaceId: string | null;
  agentId: string | null;
  agents: Agent[];
  currentAgent: Agent | null;
  setWorkspaceId: (id: string) => void;
  clearWorkspace: () => void;
  demoMode: boolean;
  setDemoMode: (v: boolean) => void;
  ensureWorkspace: () => Promise<string>;
  refreshAgents: () => Promise<Agent[]>;
  selectAgent: (agentId: string) => Promise<void>;
  createAgent: (name: string, description?: string) => Promise<Agent>;
  renameAgent: (agentId: string, name: string, description?: string) => Promise<void>;
  agentSettings: AgentSettings;
  updateAgentSettings: (patch: Partial<AgentSettings>) => void;
  resetAgentSettings: () => void;
  publishInfo: { snippet: string; url: string; key: string } | null;
  publishAgent: () => Promise<void>;
  unpublishAgent: () => Promise<void>;
  setAgentDisabled: (agentId: string, disabled: boolean) => Promise<void>;
  deleteAgent: (agentId: string) => Promise<void>;
};

const WorkspaceCtx = createContext<Ctx | null>(null);
const LS_WS = "vera.workspaceId";
const LS_AGENT = "vera.agentId";

function migrateLs(from: string, to: string) {
  try {
    if (!localStorage.getItem(to)) {
      const legacy = localStorage.getItem(from);
      if (legacy) localStorage.setItem(to, legacy);
    }
  } catch {
    /* ignore */
  }
}
migrateLs("kite.workspaceId", LS_WS);
migrateLs("kite.agentId", LS_AGENT);

function settingsFromAgent(agent: Agent): AgentSettings {
  const s = agent.settings || {};
  const agentName = String(s.agentName || agent.name || DEFAULT_AGENT_SETTINGS.agentName);
  const samples = Array.isArray(s.sampleQuestions)
    ? (s.sampleQuestions as string[]).filter((q) => typeof q === "string" && q.trim())
    : [];
  return {
    ...DEFAULT_AGENT_SETTINGS,
    agentName,
    greeting: String(s.greeting || DEFAULT_AGENT_SETTINGS.greeting),
    placeholder: String(s.placeholder || DEFAULT_AGENT_SETTINGS.placeholder),
    tone: (s.tone as AgentSettings["tone"]) || DEFAULT_AGENT_SETTINGS.tone,
    verbosity: (s.verbosity as AgentSettings["verbosity"]) || DEFAULT_AGENT_SETTINGS.verbosity,
    accent: (s.accent as AgentSettings["accent"]) || DEFAULT_AGENT_SETTINGS.accent,
    showTrustTrail: s.showTrustTrail !== false,
    showCitations: s.showCitations !== false,
    showTrustScore: s.showTrustScore !== false,
    sampleQuestions: samples.length
      ? samples
      : defaultSamplesForAgent(
          agentName,
          (s.domainProfile as { label?: string; focus?: string; entityTypes?: string[] } | undefined) ||
            null
        ),
  };
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaceId, setWorkspaceIdState] = useState<string | null>(() =>
    localStorage.getItem(LS_WS)
  );
  const [agentId, setAgentIdState] = useState<string | null>(() =>
    localStorage.getItem(LS_AGENT)
  );
  const [agents, setAgents] = useState<Agent[]>([]);
  const [demoMode, setDemoMode] = useState(false);
  const [agentSettings, setAgentSettings] = useState<AgentSettings>(() => loadAgentSettings());
  const [publishInfo, setPublishInfo] = useState<{
    snippet: string;
    url: string;
    key: string;
  } | null>(null);

  useEffect(() => {
    api.status().then((s) => setDemoMode(s.demo_mode)).catch(() => undefined);
  }, []);

  const setWorkspaceId = (id: string) => {
    localStorage.setItem(LS_WS, id);
    setWorkspaceIdState(id);
  };

  const setAgentId = (id: string) => {
    localStorage.setItem(LS_AGENT, id);
    setAgentIdState(id);
  };

  const clearWorkspace = () => {
    localStorage.removeItem(LS_WS);
    localStorage.removeItem(LS_AGENT);
    setWorkspaceIdState(null);
    setAgentIdState(null);
  };

  const applyAgent = useCallback((agent: Agent) => {
    setAgentId(agent.id);
    setWorkspaceId(agent.workspace_id);
    const next = settingsFromAgent(agent);
    saveAgentSettings(next);
    setAgentSettings(next);
    if (agent.published && agent.embed_key) {
      const origin = window.location.origin;
      setPublishInfo({
        key: agent.embed_key,
        url: `${origin}/embed/${agent.embed_key}`,
        snippet: `<script src="${origin}/widget.js" data-vera-key="${agent.embed_key}" data-vera-origin="${origin}" async></script>`,
      });
    } else {
      setPublishInfo(null);
    }
  }, []);

  const refreshAgents = useCallback(async () => {
    const list = await api.listAgents();
    setAgents(list);
    return list;
  }, []);

  const selectAgent = useCallback(
    async (id: string) => {
      const agent = await api.getAgent(id);
      applyAgent(agent);
      await refreshAgents();
    },
    [applyAgent, refreshAgents]
  );

  const createAgent = useCallback(
    async (name: string, description = "") => {
      const agent = await api.createAgent(name, description);
      applyAgent(agent);
      await refreshAgents();
      return agent;
    },
    [applyAgent, refreshAgents]
  );

  const renameAgent = useCallback(
    async (id: string, name: string, description?: string) => {
      const patch: {
        name: string;
        description?: string;
        settings: Record<string, unknown>;
      } = {
        name,
        settings: { agentName: name },
      };
      if (description !== undefined) patch.description = description;
      const agent = await api.updateAgent(id, patch);
      if (agentId === id) applyAgent(agent);
      else setAgents((list) => list.map((a) => (a.id === agent.id ? agent : a)));
      await refreshAgents();
    },
    [agentId, applyAgent, refreshAgents]
  );

  const ensureWorkspace = useCallback(async () => {
    try {
      const list = await refreshAgents();
      const cachedAgent = agentId || localStorage.getItem(LS_AGENT);
      if (cachedAgent) {
        const found = list.find((a) => a.id === cachedAgent);
        if (found) {
          applyAgent(found);
          return found.workspace_id;
        }
      }
      const cachedWs = workspaceId || localStorage.getItem(LS_WS);
      if (cachedWs) {
        const byWs = list.find((a) => a.workspace_id === cachedWs);
        if (byWs) {
          applyAgent(byWs);
          return byWs.workspace_id;
        }
        try {
          await api.getWorkspace(cachedWs);
          setWorkspaceId(cachedWs);
          return cachedWs;
        } catch {
          /* fall through */
        }
      }
      if (list.length) {
        applyAgent(list[0]);
        return list[0].workspace_id;
      }
      const created = await api.createAgent("Public Agent", "Default public-facing knowledge agent");
      applyAgent(created);
      await refreshAgents();
      return created.workspace_id;
    } catch {
      const ws = await api.createWorkspace("VERA Workspace");
      setWorkspaceId(ws.id);
      await refreshAgents().catch(() => []);
      return ws.id;
    }
  }, [agentId, workspaceId, applyAgent, refreshAgents]);

  useEffect(() => {
    void ensureWorkspace();
    // bootstrap once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateAgentSettings = (patch: Partial<AgentSettings>) => {
    setAgentSettings((prev) => {
      const next = { ...prev, ...patch };
      saveAgentSettings(next);
      if (agentId) {
        void api
          .updateAgent(agentId, {
            name: next.agentName,
            settings: next as unknown as Record<string, unknown>,
          })
          .then((agent) => {
            setAgents((list) => list.map((a) => (a.id === agent.id ? agent : a)));
          })
          .catch(() => undefined);
      }
      return next;
    });
  };

  const currentAgent = useMemo(
    () => agents.find((a) => a.id === agentId) || null,
    [agents, agentId]
  );

  const resetAgentSettings = () => {
    const next = {
      ...DEFAULT_AGENT_SETTINGS,
      agentName: currentAgent?.name || DEFAULT_AGENT_SETTINGS.agentName,
    };
    saveAgentSettings(next);
    setAgentSettings(next);
    if (agentId) {
      void api
        .updateAgent(agentId, {
          settings: next as unknown as Record<string, unknown>,
        })
        .catch(() => undefined);
    }
  };

  const publishAgent = async () => {
    if (!agentId) return;
    const pub = await api.publishAgent(agentId);
    setPublishInfo({
      key: pub.embed_key,
      url: pub.embed_url || `${window.location.origin}/embed/${pub.embed_key}`,
      snippet: pub.embed_snippet,
    });
    await refreshAgents();
  };

  const unpublishAgent = async () => {
    if (!agentId) return;
    await api.unpublishAgent(agentId);
    setPublishInfo(null);
    await refreshAgents();
  };

  const setAgentDisabled = useCallback(
    async (id: string, disabled: boolean) => {
      const agent = disabled ? await api.disableAgent(id) : await api.enableAgent(id);
      if (agentId === id) applyAgent(agent);
      await refreshAgents();
    },
    [agentId, applyAgent, refreshAgents]
  );

  const deleteAgent = useCallback(
    async (id: string) => {
      await api.deleteAgent(id);
      const list = await refreshAgents();
      if (agentId === id) {
        if (list.length) {
          applyAgent(list[0]);
        } else {
          clearWorkspace();
          setPublishInfo(null);
        }
      }
    },
    [agentId, applyAgent, refreshAgents]
  );

  const value = useMemo(
    () => ({
      workspaceId,
      agentId,
      agents,
      currentAgent,
      setWorkspaceId,
      clearWorkspace,
      demoMode,
      setDemoMode,
      ensureWorkspace,
      refreshAgents,
      selectAgent,
      createAgent,
      renameAgent,
      agentSettings,
      updateAgentSettings,
      resetAgentSettings,
      publishInfo,
      publishAgent,
      unpublishAgent,
      setAgentDisabled,
      deleteAgent,
    }),
    [
      workspaceId,
      agentId,
      agents,
      currentAgent,
      demoMode,
      agentSettings,
      publishInfo,
      ensureWorkspace,
      refreshAgents,
      selectAgent,
      createAgent,
      renameAgent,
      setAgentDisabled,
      deleteAgent,
    ]
  );

  return <WorkspaceCtx.Provider value={value}>{children}</WorkspaceCtx.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceCtx);
  if (!ctx) throw new Error("WorkspaceProvider missing");
  return ctx;
}
