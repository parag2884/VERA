/** Stable pastel palette — assigned by hashing whatever type string the graph returns. */
const PALETTE = [
  "#6c5ce7",
  "#0f9d8a",
  "#e85d2a",
  "#d4940a",
  "#d63384",
  "#2563eb",
  "#16a34a",
  "#71717a",
  "#dc2626",
  "#0891b2",
  "#7c3aed",
  "#ca8a04",
];

/** Optional plural polish for a few structural types. Everything else is title-cased as-is. */
const LABEL_OVERRIDES: Record<string, string> = {
  Document: "Documents",
  Chunk: "Chunks",
  Person: "People",
  Organization: "Organizations",
};

function hashType(type: string): number {
  let h = 0;
  for (let i = 0; i < type.length; i++) {
    h = (h * 31 + type.charCodeAt(i)) >>> 0;
  }
  return h;
}

/** Human label from any type string (Clause, Campaign, JobRole, …). */
export function typeLabel(type: string): string {
  if (!type) return "Unknown";
  if (LABEL_OVERRIDES[type]) return LABEL_OVERRIDES[type];
  // Title Case + light pluralization for legend counts
  const spaced = type
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
  const titled = spaced.replace(/\b\w/g, (c) => c.toUpperCase());
  if (/s$/i.test(titled) || /people$/i.test(titled)) return titled;
  if (/y$/i.test(titled)) return `${titled.slice(0, -1)}ies`;
  return `${titled}s`;
}

/** Deterministic color for any type — same type always same color across sessions. */
export function typeColor(type: string): string {
  if (!type) return PALETTE[0];
  return PALETTE[hashType(type) % PALETTE.length];
}

export function typeMeta(type: string): { color: string; label: string } {
  return { color: typeColor(type), label: typeLabel(type) };
}
