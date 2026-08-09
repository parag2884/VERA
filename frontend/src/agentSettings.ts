export type AnswerTone =
  | "professional"
  | "friendly"
  | "concise"
  | "formal"
  | "executive";

export type Verbosity = "short" | "balanced" | "detailed";

export type AccentPreset = "teal" | "navy" | "amber" | "coral";

export type AgentSettings = {
  agentName: string;
  greeting: string;
  tone: AnswerTone;
  verbosity: Verbosity;
  accent: AccentPreset;
  showTrustTrail: boolean;
  showCitations: boolean;
  showTrustScore: boolean;
  /** Publisher setting: stream answers on published embed / widget */
  embedStreaming: boolean;
  placeholder: string;
  /** Suggested chips in chat — leave empty to auto-pick from agent name */
  sampleQuestions: string[];
};

export const DEFAULT_AGENT_SETTINGS: AgentSettings = {
  agentName: "Public Agent",
  greeting: "Ask anything about your connected knowledge. I’ll answer with a Trust Trail — or clarify / refuse when proof is missing.",
  tone: "professional",
  verbosity: "balanced",
  accent: "coral",
  showTrustTrail: true,
  showCitations: true,
  showTrustScore: true,
  embedStreaming: true,
  placeholder: "Ask about your connected knowledge…",
  sampleQuestions: [],
};

export const TONE_OPTIONS: Array<{ id: AnswerTone; label: string; hint: string }> = [
  { id: "professional", label: "Professional", hint: "Clear, neutral, business-ready" },
  { id: "friendly", label: "Friendly", hint: "Warm and approachable" },
  { id: "concise", label: "Concise", hint: "Short answers, minimal fluff" },
  { id: "formal", label: "Formal", hint: "Policy / legal register" },
  { id: "executive", label: "Executive", hint: "Decision-ready brief" },
];

export const VERBOSITY_OPTIONS: Array<{ id: Verbosity; label: string }> = [
  { id: "short", label: "Short" },
  { id: "balanced", label: "Balanced" },
  { id: "detailed", label: "Detailed" },
];

export const ACCENT_OPTIONS: Array<{ id: AccentPreset; label: string; swatch: string }> = [
  { id: "coral", label: "Coral", swatch: "#ff6a3d" },
  { id: "teal", label: "Teal", swatch: "#0f9d8a" },
  { id: "navy", label: "Navy", swatch: "#152238" },
  { id: "amber", label: "Amber", swatch: "#d97706" },
];

const LS_KEY = "vera.agentSettings";
const LS_KEY_LEGACY = "kite.agentSettings";

export function loadAgentSettings(): AgentSettings {
  try {
    const raw = localStorage.getItem(LS_KEY) || localStorage.getItem(LS_KEY_LEGACY);
    if (!raw) return { ...DEFAULT_AGENT_SETTINGS };
    return { ...DEFAULT_AGENT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_AGENT_SETTINGS };
  }
}

export function saveAgentSettings(settings: AgentSettings) {
  localStorage.setItem(LS_KEY, JSON.stringify(settings));
}
