import { useEffect, useMemo, useRef, useState } from "react";
import { forceCollide } from "d3-force-3d";
import ForceGraph2D from "react-force-graph-2d";
import { Link } from "react-router-dom";
import { api, GraphData } from "../api/client";
import { typeColor, typeLabel, typeMeta } from "../graphTypes";
import { useWorkspace } from "../state";

type Lens = "structure" | "asserted" | "conflict";
type GraphNode = {
  id: string;
  name: string;
  type: string;
  degree?: number;
  r?: number;
  x?: number;
  y?: number;
};
type GraphLink = {
  source: string | GraphNode;
  target: string | GraphNode;
  rel: string;
  evidence: boolean;
  cls: string;
};

/** Compact radii like pt_knowledge_graph_light, scaled for denser graphs. */
function nodeRadius(n: Pick<GraphNode, "type" | "degree" | "r">): number {
  if (typeof n.r === "number" && n.r > 0) return n.r;
  const deg = Math.max(0, n.degree || 0);
  // Only structural Document type gets a mild boost; everything else is degree-driven
  const typeBoost = n.type === "Document" ? 1.1 : 0;
  const raw = 4.2 + typeBoost + Math.sqrt(deg) * 1.05;
  return Math.max(3.8, Math.min(11, raw));
}

/** Soft screen-space clamp so zoom-in doesn't create giant bubbles. */
function paintRadius(
  n: Pick<GraphNode, "type" | "degree" | "r">,
  globalScale: number,
  emphasize: boolean
): number {
  const base = nodeRadius(n) * (emphasize ? 1.15 : 1);
  const scale = Math.max(0.15, globalScale || 1);
  const screenPx = Math.max(3.2, Math.min(12.5, base * scale));
  return screenPx / scale;
}

function linkEnds(l: GraphLink): [string, string] {
  const s = typeof l.source === "string" ? l.source : l.source.id;
  const t = typeof l.target === "string" ? l.target : l.target.id;
  return [s, t];
}

export default function KnowledgeMap() {
  const {
    workspaceId,
    ensureWorkspace,
    agents,
    agentId,
    currentAgent,
    selectAgent,
    refreshAgents,
  } = useWorkspace();
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lens, setLens] = useState<Lens>("structure");
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const neighborIdsRef = useRef<Set<string>>(new Set());
  const queryRef = useRef("");
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const fgRef = useRef<any>(null);
  const fittedRef = useRef(false);
  const [size, setSize] = useState({ w: 900, h: 620 });

  useEffect(() => {
    void refreshAgents().catch(() => undefined);
  }, [refreshAgents]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 2 && h > 2) setSize({ w, h });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [agentId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      setGraph(null);
      setSelected(null);
      fittedRef.current = false;
      try {
        const ws = workspaceId || (await ensureWorkspace());
        const g = await api.graph(ws);
        if (!cancelled) setGraph(g);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, agentId, ensureWorkspace]);

  const assertedCount =
    graph?.edges.filter((e) => e.edge_class === "asserted_fact" && e.has_evidence).length || 0;
  const docEdgeCount = graph?.edges.filter((e) => e.edge_class === "documentary").length || 0;

  const baseData = useMemo(() => {
    if (!graph) return { nodes: [] as GraphNode[], links: [] as GraphLink[] };

    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const chunkToDoc = new Map<string, string>();
    for (const e of graph.edges) {
      if (e.rel_type === "CONTAINS") chunkToDoc.set(e.dst, e.src);
    }

    const links: GraphLink[] = [];
    const nodeIds = new Set<string>();
    const seenLink = new Set<string>();

    const addLink = (
      src: string,
      dst: string,
      rel: string,
      evidence: boolean,
      cls: string
    ) => {
      if (!byId.has(src) || !byId.has(dst)) return;
      if (src === dst) return;
      if (byId.get(src)?.type === "Chunk" || byId.get(dst)?.type === "Chunk") return;
      const key = `${src}|${dst}|${rel}|${cls}`;
      const keyRev = `${dst}|${src}|${rel}|${cls}`;
      if (seenLink.has(key) || seenLink.has(keyRev)) {
        // Prefer evidence-bearing duplicate
        if (evidence) {
          const idx = links.findIndex((l) => {
            const [a, b] = linkEnds(l);
            return l.rel === rel && l.cls === cls && ((a === src && b === dst) || (a === dst && b === src));
          });
          if (idx >= 0 && !links[idx].evidence) links[idx] = { ...links[idx], evidence: true };
        }
        return;
      }
      seenLink.add(key);
      nodeIds.add(src);
      nodeIds.add(dst);
      links.push({ source: src, target: dst, rel, evidence, cls });
    };

    if (lens === "conflict") {
      for (const e of graph.edges) {
        if (
          e.edge_class === "asserted_fact" &&
          ["CONFLICTS_WITH", "SUPERSEDES"].includes(e.rel_type)
        ) {
          addLink(e.src, e.dst, e.rel_type, e.has_evidence, e.edge_class);
        }
      }
    } else if (lens === "asserted") {
      for (const e of graph.edges) {
        if (e.edge_class === "asserted_fact") {
          addLink(e.src, e.dst, e.rel_type, e.has_evidence, e.edge_class);
        }
      }
    } else {
      for (const e of graph.edges) {
        if (e.edge_class === "asserted_fact") {
          addLink(e.src, e.dst, e.rel_type, e.has_evidence, e.edge_class);
          continue;
        }
        if (e.rel_type === "DEFINED_IN") {
          addLink(e.src, e.dst, e.rel_type, e.has_evidence, e.edge_class);
          continue;
        }
        if (e.rel_type === "MENTIONS") {
          const docId = chunkToDoc.get(e.src);
          if (docId) addLink(docId, e.dst, "MENTIONS", e.has_evidence, "documentary");
        }
      }
      for (const n of graph.nodes) {
        if (n.type === "Document") nodeIds.add(n.id);
      }
      if (links.length === 0) {
        for (const n of graph.nodes) {
          if (n.type !== "Chunk") nodeIds.add(n.id);
        }
      }
    }

    const degree = new Map<string, number>();
    for (const l of links) {
      const [s, t] = linkEnds(l);
      degree.set(s, (degree.get(s) || 0) + 1);
      degree.set(t, (degree.get(t) || 0) + 1);
    }

    return {
      nodes: graph.nodes
        .filter((n) => nodeIds.has(n.id) && n.type !== "Chunk")
        .map((n) => {
          const deg = degree.get(n.id) || 0;
          const node = { id: n.id, name: n.name, type: n.type, degree: deg };
          return { ...node, r: nodeRadius(node) };
        }),
      links,
    };
  }, [graph, lens]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of baseData.nodes) {
      counts.set(n.type, (counts.get(n.type) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [baseData.nodes]);

  const q = query.trim().toLowerCase();
  selectedIdRef.current = selected?.id ?? null;
  queryRef.current = q;

  const neighborIds = useMemo(() => {
    const ids = new Set<string>();
    if (!selected) return ids;
    ids.add(selected.id);
    for (const l of baseData.links) {
      const [s, t] = linkEnds(l);
      if (s === selected.id) ids.add(t);
      if (t === selected.id) ids.add(s);
    }
    return ids;
  }, [selected, baseData.links]);
  neighborIdsRef.current = neighborIds;

  const data = useMemo(() => {
    const visibleIds = new Set(
      baseData.nodes
        .filter((n) => !hiddenTypes.has(n.type))
        .filter((n) => !q || n.name.toLowerCase().includes(q) || n.type.toLowerCase().includes(q))
        .map((n) => n.id)
    );

    if (q) {
      const byType = new Map(baseData.nodes.map((n) => [n.id, n.type]));
      for (const l of baseData.links) {
        const [s, t] = linkEnds(l);
        if (visibleIds.has(s) || visibleIds.has(t)) {
          if (!hiddenTypes.has(byType.get(s) || "")) visibleIds.add(s);
          if (!hiddenTypes.has(byType.get(t) || "")) visibleIds.add(t);
        }
      }
    }

    return {
      nodes: baseData.nodes.filter((n) => visibleIds.has(n.id)),
      links: baseData.links.filter((l) => {
        const [s, t] = linkEnds(l);
        return visibleIds.has(s) && visibleIds.has(t);
      }),
    };
  }, [baseData, hiddenTypes, q]);

  const selectedLinks = useMemo(() => {
    if (!selected) return [];
    return baseData.links
      .filter((l) => {
        const [s, t] = linkEnds(l);
        return s === selected.id || t === selected.id;
      })
      .map((l) => {
        const [s, t] = linkEnds(l);
        const otherId = s === selected.id ? t : s;
        const other = baseData.nodes.find((n) => n.id === otherId);
        return {
          rel: l.rel,
          direction: s === selected.id ? "out" : "in",
          otherId,
          other: other?.name || otherId,
          otherType: other?.type || "",
          evidence: l.evidence,
        };
      });
  }, [selected, baseData]);

  useEffect(() => {
    fittedRef.current = false;
    const fg = fgRef.current;
    if (!fg || !data.nodes.length || size.w < 8 || size.h < 8) return;

    // Scale forces to the live canvas so the weave spreads into available space
    const n = Math.max(data.nodes.length, 1);
    const density = Math.sqrt((size.w * size.h) / n);
    const linkDist = Math.max(48, Math.min(150, density * 0.62));
    const charge = -Math.max(120, Math.min(360, density * 1.35));
    fg.d3Force?.("charge")?.strength?.(charge);
    const linkForce = fg.d3Force?.("link");
    linkForce?.distance?.(linkDist);
    linkForce?.strength?.(0.28);
    fg.d3Force?.("center")?.strength?.(0.02);
    // Very light centering — let the graph occupy the viewport, not a center blob
    fg.d3Force?.("x")?.strength?.(0.012);
    fg.d3Force?.("y")?.strength?.(0.012);
    fg.d3Force?.(
      "collide",
      forceCollide((node: GraphNode) => nodeRadius(node) + 12).iterations(2)
    );
    fg.d3ReheatSimulation?.();

    const fit = (pad: number, bump = 1) => {
      try {
        fg.zoomToFit?.(520, pad);
        if (bump > 1) {
          const z = fg.zoom?.() ?? 1;
          fg.zoom?.(z * bump, 280);
        }
        fittedRef.current = true;
      } catch {
        /* ignore */
      }
    };
    // Tight padding + slight zoom-in so the weave fills the canvas
    const t1 = window.setTimeout(() => fit(36, 1.08), 700);
    const t2 = window.setTimeout(() => fit(28, 1.12), 2000);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [data, size.w, size.h, lens]);

  function focusNode(node: GraphNode) {
    setSelected(node);
    const fg = fgRef.current;
    if (!fg || node.x == null || node.y == null) return;
    try {
      fg.centerAt?.(node.x, node.y, 400);
      const z = fg.zoom?.() ?? 1;
      if (z < 1.2) fg.zoom?.(1.35, 400);
    } catch {
      /* ignore */
    }
  }

  const agentLabel = currentAgent?.name || "Active agent";
  const domainLabel = String(
    (currentAgent?.settings?.domainProfile as { label?: string } | undefined)?.label || ""
  ).trim();
  const emptyHint = (() => {
    if (loading || !graph) return `Loading map for ${agentLabel}…`;
    if (graph.nodes.length === 0) {
      return `No graph for ${agentLabel} yet — attach documents while this agent is active.`;
    }
    if (lens === "asserted" && assertedCount === 0) {
      return `${agentLabel} has structural edges but no asserted facts yet. Try Structure.`;
    }
    if (lens === "conflict") return `No supersede / conflict edges for ${agentLabel}.`;
    if (data.nodes.length === 0) return "No nodes match this search or filter.";
    return `${agentLabel}: switch lens or rebuild from Knowledge.`;
  })();

  function toggleType(type: string) {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  if (!agents.length) {
    return (
      <div className="map-page map-focus map-focus-empty">
        <h2>Create an agent first</h2>
        <p className="muted">Maps need an agent with woven knowledge.</p>
        <Link className="btn btn-primary" to="/agent">
          Go to Agents
        </Link>
      </div>
    );
  }

  return (
    <div className="map-page map-focus">
      {error && <p className="map-focus-error">{error}</p>}

      <div className={`map-studio${selected ? "" : " panel-closed"}`}>
        <div className="map-canvas" ref={wrapRef}>
          <div className="map-toolbar">
            <label className="map-agent-picker">
              <span>Agent</span>
              <select
                value={agentId || ""}
                aria-label="Select agent map"
                onChange={(e) => {
                  if (e.target.value) void selectAgent(e.target.value);
                }}
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {typeof a.counts?.nodes === "number" ? ` · ${a.counts.nodes}n` : ""}
                  </option>
                ))}
              </select>
            </label>
            <input
              className="map-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${baseData.nodes.length} nodes…`}
              autoComplete="off"
            />
            <div className="map-lens">
              {(
                [
                  ["structure", "Structure"],
                  ["asserted", "Facts"],
                  ["conflict", "Conflicts"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`map-lens-btn ${lens === id ? "active" : ""}`}
                  onClick={() => setLens(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {domainLabel ? <span className="map-domain-chip">{domainLabel}</span> : null}
            <button
              type="button"
              className="map-fit-btn"
              onClick={() => {
                try {
                  const fg = fgRef.current;
                  fg?.zoomToFit?.(500, 24);
                  const z = fg?.zoom?.() ?? 1;
                  fg?.zoom?.(z * 1.12, 280);
                } catch {
                  /* ignore */
                }
              }}
              title="Fit graph to screen"
            >
              Fit
            </button>
            <Link className="map-knowledge-link" to="/agent">
              Knowledge
            </Link>
          </div>

          {typeCounts.length > 0 && (
            <div className="map-legend">
              {typeCounts.map(([type, count]) => {
                const meta = typeMeta(type);
                const off = hiddenTypes.has(type);
                return (
                  <button
                    key={type}
                    type="button"
                    className={`map-legend-item ${off ? "off" : ""}`}
                    onClick={() => toggleType(type)}
                    title={off ? `Show ${meta.label}` : `Hide ${meta.label}`}
                  >
                    <i style={{ background: meta.color }} />
                    <span>
                      {meta.label} ({count})
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          <div className="map-stats">
            <div className="map-stat">
              <b>{loading ? "…" : data.nodes.length}</b> nodes
            </div>
            <div className="map-stat">
              <b>{loading ? "…" : data.links.length}</b> edges
            </div>
            <div className="map-stat">
              <b>{loading ? "…" : assertedCount}</b> evidence
            </div>
            <div className="map-stat">
              <b>{loading ? "…" : docEdgeCount}</b> structural
            </div>
          </div>

          {data.nodes.length > 0 && size.w > 8 && size.h > 8 ? (
            <ForceGraph2D
              key={`${agentId || "none"}-${lens}`}
              ref={fgRef}
              width={size.w}
              height={size.h}
              graphData={data}
              backgroundColor="rgba(0,0,0,0)"
              minZoom={0.2}
              maxZoom={5}
              nodeLabel={(n: GraphNode) =>
                `${n.name} (${n.type}${typeof n.degree === "number" ? ` · ${n.degree} links` : ""})`
              }
              linkLabel={(l: GraphLink) => l.rel || ""}
              onNodeClick={(n: GraphNode) => focusNode(n)}
              onBackgroundClick={() => setSelected(null)}
              onNodeDragEnd={() => {
                fgRef.current?.d3ReheatSimulation?.();
              }}
              onEngineStop={() => {
                if (fittedRef.current) return;
                try {
                  const fg = fgRef.current;
                  fg?.zoomToFit?.(400, 28);
                  const z = fg?.zoom?.() ?? 1;
                  fg?.zoom?.(z * 1.1, 200);
                  fittedRef.current = true;
                } catch {
                  /* ignore */
                }
              }}
              cooldownTicks={220}
              cooldownTime={7000}
              warmupTicks={60}
              d3AlphaDecay={0.022}
              d3VelocityDecay={0.35}
              enableNodeDrag
              nodeCanvasObject={(node: GraphNode, ctx, globalScale) => {
                const label = node.name || "";
                const isSel = selectedIdRef.current === node.id;
                const qq = queryRef.current;
                const match = Boolean(qq && label.toLowerCase().includes(qq));
                const emphasize = isSel || match;
                const hasFocus = Boolean(selectedIdRef.current);
                const inNeighborhood = !hasFocus || neighborIdsRef.current.has(node.id);
                const sizePx = paintRadius(node, globalScale, emphasize);
                const color = typeColor(node.type);
                const deg = node.degree || 0;
                const boldLabel = emphasize || deg >= 10;

                ctx.save();
                if (hasFocus && !inNeighborhood) ctx.globalAlpha = 0.18;
                ctx.beginPath();
                ctx.arc(node.x || 0, node.y || 0, sizePx, 0, 2 * Math.PI);
                ctx.globalAlpha = (hasFocus && !inNeighborhood ? 0.08 : emphasize ? 0.88 : 0.14);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.globalAlpha = hasFocus && !inNeighborhood ? 0.25 : 1;
                ctx.lineWidth = (emphasize ? 2.2 : 1.35) / globalScale;
                ctx.strokeStyle = isSel ? "#1a1d26" : color;
                ctx.stroke();

                const showLabel =
                  emphasize ||
                  (inNeighborhood &&
                    (globalScale >= 1.15 ||
                      (globalScale >= 0.7 && (boldLabel || deg >= 4)) ||
                      (globalScale >= 0.45 && deg >= 8)));
                if (showLabel) {
                  const fontScreen = boldLabel ? 11 : 10;
                  const fontSize = fontScreen / globalScale;
                  const short =
                    label.length > 28 && globalScale < 1.2
                      ? `${label.slice(0, 26)}…`
                      : label.slice(0, 40);
                  ctx.font = `${boldLabel ? 500 : 400} ${fontSize}px DM Sans, Sora, Segoe UI, sans-serif`;
                  ctx.textAlign = "center";
                  ctx.textBaseline = "top";
                  ctx.fillStyle = emphasize ? "#1a1d26" : "#3a4050";
                  ctx.fillText(short, node.x || 0, (node.y || 0) + sizePx + 3.5 / globalScale);
                }
                ctx.restore();
              }}
              nodePointerAreaPaint={(node: GraphNode, color, ctx, globalScale) => {
                const hit =
                  paintRadius(node, globalScale || 1, false) +
                  4 / Math.max(0.2, globalScale || 1);
                ctx.beginPath();
                ctx.arc(node.x || 0, node.y || 0, hit, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
              }}
              linkColor={(l: GraphLink) => {
                const [s, t] = linkEnds(l);
                const sel = selectedIdRef.current;
                const focused = sel && (s === sel || t === sel);
                if (sel && !focused) return "rgba(180,184,192,0.12)";
                if (["CONFLICTS_WITH", "SUPERSEDES"].includes(l.rel)) return "#d4940a";
                if (l.cls === "asserted_fact") {
                  return focused ? "rgba(70,110,210,0.95)" : "rgba(90,120,200,0.7)";
                }
                if (l.cls === "documentary") {
                  return focused ? "rgba(120,128,140,0.7)" : "rgba(160,168,180,0.4)";
                }
                return "rgba(140,148,162,0.5)";
              }}
              linkDirectionalArrowLength={0}
              linkWidth={(l: GraphLink) => {
                const [s, t] = linkEnds(l);
                const sel = selectedIdRef.current;
                const focused = Boolean(sel && (s === sel || t === sel));
                const base =
                  l.cls === "asserted_fact" ? (l.evidence ? 1.15 : 0.8) : l.evidence ? 0.7 : 0.4;
                return focused ? base + 0.7 : base;
              }}
            />
          ) : (
            <div className="map-empty">{emptyHint}</div>
          )}
        </div>

        <aside className="map-side">
          {selected ? (
            <>
              <div className="map-side-head">
                <button
                  type="button"
                  className="map-side-close"
                  onClick={() => setSelected(null)}
                  aria-label="Close"
                >
                  ×
                </button>
                <div className="map-side-cat" style={{ color: typeColor(selected.type) }}>
                  {typeLabel(selected.type)}
                </div>
                <h3>{selected.name}</h3>
                <p className="muted">
                  {selected.degree ?? 0} connections in this lens · {agentLabel}
                </p>
              </div>
              <div className="map-side-body">
                <div className="map-side-section">Relationships · {selectedLinks.length}</div>
                {selectedLinks.length === 0 && (
                  <p className="muted" style={{ fontSize: "0.82rem" }}>
                    No edges in this lens for this node.
                  </p>
                )}
                <ul className="map-edge-list">
                  {selectedLinks.map((e, i) => (
                    <li key={`${e.rel}-${e.otherId}-${i}`}>
                      <button
                        type="button"
                        className="map-edge-jump"
                        onClick={() => {
                          const n = data.nodes.find((x) => x.id === e.otherId);
                          if (n) focusNode(n);
                        }}
                      >
                        <span className="map-edge-rel">{e.rel}</span>
                        <span className="map-edge-dir">{e.direction === "out" ? "→" : "←"}</span>
                        <span className="map-edge-other">{e.other}</span>
                        <em>{e.otherType}</em>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          ) : (
            <div className="map-side-empty">
              <div aria-hidden>◈</div>
              <p>
                Click any node on the graph
                <br />
                to explore relationships
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
