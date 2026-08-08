/** Suggested prompts from the agent's inferred domain — not a fixed industry pack. */

export type DomainProfileLite = {
  label?: string;
  focus?: string;
  entityTypes?: string[];
};

export function defaultSamplesForAgent(
  agentName: string,
  domain?: DomainProfileLite | null
): string[] {
  const label = (domain?.label || "").trim();
  const focus = (domain?.focus || "").trim();
  const types = (domain?.entityTypes || []).filter(Boolean).slice(0, 4);
  const name = (agentName || "").trim() || "this agent";

  if (label || types.length) {
    const typeHint = types.length ? types.slice(0, 2).join(" / ") : "key entities";
    return [
      `What documents are connected for ${label || name}?`,
      `Give a short overview of this ${label || "knowledge"} base`,
      `How are the main ${typeHint} related?`,
      focus
        ? `What should I verify about: ${focus.length > 80 ? `${focus.slice(0, 77)}…` : focus}`
        : "Ask something that needs a Trust Trail to prove",
    ];
  }

  return [
    `What documents are connected to ${name}?`,
    "Give a short overview of the knowledge base",
    "What are the most important entities in the graph?",
    "Ask something that needs a Trust Trail to prove",
  ];
}

export function parseSampleLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(0, 8);
}
