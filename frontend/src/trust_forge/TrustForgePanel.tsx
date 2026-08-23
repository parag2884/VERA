import { useEffect, useState } from "react";
import {
  api,
  formatApiError,
  type TrustForgeDelta,
  type TrustForgeRun,
} from "../api/client";

function ImprovementCard({
  title,
  delta,
}: {
  title: string;
  delta: TrustForgeDelta;
}) {
  const passed = delta.newly_passed || [];
  const failed = delta.newly_failed || [];
  const still = delta.still_failed || [];
  const heal = delta.heal || {};
  const aliases = Number(heal.aliases_removed ?? 0);
  const retyped = Number(heal.junk_persons_retyped ?? 0);
  const site = Number(heal.site_part_of_edges ?? 0);
  const pins = Number(heal.facts_pinned ?? 0);

  return (
    <div className="trust-forge-improve">
      <div className="nav-label" style={{ marginBottom: 6 }}>
        {title}
      </div>
      {delta.vs_gen && delta.fitness_before != null ? (
        <p className="trust-forge-improve-score mono">
          {Number(delta.fitness_before).toFixed(1)}% →{" "}
          {Number(delta.fitness_after ?? 0).toFixed(1)}%
          {delta.fitness_delta != null ? (
            <span className={delta.fitness_delta >= 0 ? "up" : "down"}>
              {" "}
              ({delta.fitness_delta >= 0 ? "+" : ""}
              {Number(delta.fitness_delta).toFixed(1)} pts)
            </span>
          ) : null}
        </p>
      ) : (
        <p className="trust-forge-improve-score mono">
          Baseline {Number(delta.fitness_after ?? 0).toFixed(1)}%
        </p>
      )}
      {(aliases > 0 || retyped > 0 || site > 0 || pins > 0) && (
        <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 0.45rem" }}>
          Heal: −{aliases} aliases
          {retyped ? `, ${retyped} persons retyped` : ""}
          {site ? `, ${site} site PART_OF edges` : ""}
          {pins ? `, ${pins} failed-fact pins` : ""}.
        </p>
      )}
      {passed.length > 0 ? (
        <div className="trust-forge-improve-block">
          <strong>Now passing (were failing)</strong>
          <ul>
            {passed.map((c) => (
              <li key={c.id}>
                <span className="ok">✓ {c.id}</span>
                {c.was_fail_kind ? (
                  <span className="muted"> was {c.was_fail_kind}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : delta.vs_gen ? (
        <p className="muted" style={{ fontSize: "0.8rem" }}>
          No newly passing cases this generation — % change may be from the same set
          or rounding; check still-failing list.
        </p>
      ) : null}
      {failed.length > 0 && (
        <div className="trust-forge-improve-block warn">
          <strong>Regressed</strong>
          <ul>
            {failed.map((c) => (
              <li key={c.id}>
                ✗ {c.id}
                {c.fail_kind ? <span className="muted"> ({c.fail_kind})</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {still.length > 0 && (
        <details className="trust-forge-improve-details">
          <summary>
            Still failing ({still.length})
          </summary>
          <ul>
            {still.slice(0, 12).map((c) => (
              <li key={c.id}>
                {c.id}
                {c.fail_kind ? <span className="muted"> · {c.fail_kind}</span> : null}
              </li>
            ))}
            {still.length > 12 ? <li className="muted">…and {still.length - 12} more</li> : null}
          </ul>
        </details>
      )}
    </div>
  );
}

type Props = {
  workspaceId: string | null;
  agentId: string | null;
  agentName?: string;
  layout?: "card" | "page";
  onRunChange?: (run: TrustForgeRun | null) => void;
};

function phaseLabel(phase?: string) {
  switch (phase) {
    case "starting":
      return "Starting";
    case "healing":
      return "Healing graph";
    case "evaluating":
      return "Scoring cases";
    case "generation_done":
      return "Generation done";
    case "completed":
      return "Complete";
    case "stopped":
      return "Stopped";
    case "failed":
      return "Failed";
    default:
      return phase || "Idle";
  }
}

export default function TrustForgePanel({
  workspaceId,
  agentId,
  agentName,
  layout = "card",
  onRunChange,
}: Props) {
  const [threshold, setThreshold] = useState(95);
  const [run, setRun] = useState<TrustForgeRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pulse, setPulse] = useState(0);
  const page = layout === "page";

  useEffect(() => {
    onRunChange?.(run);
  }, [run, onRunChange]);

  const active =
    run && (run.status === "queued" || run.status === "running") ? run : null;
  const progress = run?.progress || {};
  const caseIndex = Number(progress.case_index || 0);
  const caseTotal = Number(progress.case_total || 0);
  const casePct =
    caseTotal > 0 ? Math.min(100, Math.round((caseIndex / caseTotal) * 100)) : active ? 8 : 0;
  const log = progress.log || [];

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setPulse((n) => n + 1), 700);
    return () => window.clearInterval(id);
  }, [active?.id, !!active]);

  useEffect(() => {
    if (!workspaceId || !active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await api.getTrustForgeRun(workspaceId, active.id);
        if (!cancelled) setRun(next);
      } catch (e) {
        if (!cancelled) setErr(formatApiError(e, "forge"));
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [workspaceId, active?.id]);

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    (async () => {
      try {
        const { runs } = await api.listTrustForgeRuns(workspaceId);
        if (!cancelled && runs[0]) setRun(runs[0]);
      } catch {
        /* no prior runs */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, agentId]);

  async function onStart() {
    if (!workspaceId) return;
    setBusy(true);
    setErr(null);
    try {
      const started = await api.startTrustForge(workspaceId, {
        agent_id: agentId || undefined,
        threshold,
        max_generations: 8,
        stall_generations: 3,
      });
      setRun(started);
    } catch (e) {
      setErr(formatApiError(e, "forge"));
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    if (!workspaceId || !run) return;
    setBusy(true);
    setErr(null);
    try {
      const stopped = await api.stopTrustForgeRun(workspaceId, run.id);
      setRun(stopped);
    } catch (e) {
      setErr(formatApiError(e, "forge"));
    } finally {
      setBusy(false);
    }
  }

  const curve = run?.fitness_curve || run?.generations?.map((g) => g.fitness) || [];
  const suiteLabel = run?.suite_path
    ? run.suite_path.split(/[/\\]/).slice(-2).join("/")
    : "auto (agent golden suite)";
  const liveImprove = progress.improvement;
  const genImproves = (run?.generations || []).filter((g) => g.delta?.vs_gen);
  const latestImprove =
    liveImprove?.vs_gen || liveImprove?.fitness_after != null
      ? liveImprove
      : run?.latest_improvement || genImproves[genImproves.length - 1]?.delta;

  return (
    <div
      className={`panel trust-forge-panel${active ? " is-live" : ""}${page ? " is-page" : ""}`}
      style={{ marginBottom: page ? 0 : "1.15rem" }}
    >
      {!page && (
        <div className="panel-head">
          <div>
            <h3>Trust Forge</h3>
            <p>
              Climb golden-suite fitness for{" "}
              <strong>{agentName || "this agent"}</strong> only — heal KG hygiene, re-eval,
              stop at threshold or plateau. Other agents are untouched.
            </p>
          </div>
        </div>
      )}
      {page && (
        <div className="panel-head">
          <div>
            <h3>Evaluation</h3>
            <p>
              Locked golden suite for <strong>{agentName || "this workspace"}</strong>. Heal
              never recrawls the site.
            </p>
          </div>
        </div>
      )}

      <div className="ops-toolbar">
        <label className="ops-threshold">
          <span className="muted">Pass threshold</span>
          <div>
            <input
              type="range"
              min={90}
              max={100}
              step={1}
              value={threshold}
              disabled={!!active || busy}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
            <span className="mono">{threshold}%</span>
          </div>
        </label>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!workspaceId || busy || !!active}
          onClick={() => void onStart()}
        >
          Start evaluation
        </button>
        {active && (
          <button type="button" className="btn" disabled={busy} onClick={() => void onStop()}>
            Stop
          </button>
        )}
      </div>

      {err && (
        <div className="ops-alert" style={{ marginBottom: "0.85rem" }}>
          {err}
        </div>
      )}

      {active && (
        <div className="trust-forge-live" aria-live="polite">
          <div className="trust-forge-live-head">
            <span className="trust-forge-pulse" data-tick={pulse % 3} />
            <div>
              <strong>{phaseLabel(progress.phase)}</strong>
              <div className="trust-forge-live-msg">
                {progress.message || "Working on this workspace…"}
              </div>
            </div>
            <div className="trust-forge-live-meta mono">
              gen {run?.generation ?? 0}/{run?.max_generations ?? 8}
              {caseTotal > 0 ? ` · case ${caseIndex}/${caseTotal}` : ""}
            </div>
          </div>
          <div className="trust-forge-bar">
            <div className="trust-forge-bar-fill" style={{ width: `${casePct}%` }} />
          </div>
          {(progress.passed_so_far != null || progress.failed_so_far != null) && (
            <div className="trust-forge-live-stats mono">
              pass {progress.passed_so_far ?? 0} · fail {progress.failed_so_far ?? 0}
              {progress.case_id ? ` · now ${progress.case_id}` : ""}
            </div>
          )}
          {(progress.question || progress.got_answer) && (
            <div className="trust-forge-live-qa">
              {progress.question ? (
                <p>
                  <span className="label">Q</span> {progress.question}
                </p>
              ) : null}
              {progress.expected_answer ? (
                <p className="expected">
                  <span className="label">Expected</span> {progress.expected_answer}
                </p>
              ) : null}
              {progress.got_answer ? (
                <p className={progress.case_pass ? "got ok" : "got bad"}>
                  <span className="label">Got</span> {progress.got_answer}
                </p>
              ) : null}
            </div>
          )}
          {log.length > 0 && (
            <ul className="trust-forge-log">
              {log.slice(-8).map((line, i) => (
                <li key={`${i}-${line}`}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {run ? (
        <div className="bento-table-wrap" style={{ marginBottom: "0.85rem" }}>
          <table className="agent-table agent-table-auto">
            <thead>
              <tr>
                <th>Last run</th>
                <th>Status</th>
                <th className="num">Fitness</th>
                <th>Generation</th>
                <th>Suite</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{active ? "In progress" : "Completed run"}</td>
                <td>{run.status}</td>
                <td className="num">
                  {active || Number(run.generations?.[0]?.total ?? -1) === 0
                    ? "—"
                    : `${Number(run.best_fitness).toFixed(1)}%`}
                </td>
                <td>
                  {run.generation} / {run.max_generations}
                </td>
                <td className="primary muted">{suiteLabel}</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          No evaluations yet. Needs ingested knowledge and a golden file with cases[] for this
          agent name.
        </p>
      )}
      {run && !active && Number(run.generations?.[0]?.total ?? -1) === 0 && (
        <div className="ops-alert" style={{ marginBottom: "0.85rem" }}>
          That run scored 0 cases — the golden file had no questions. Fitness is blank until
          cases are scored. This is not a graph rebuild. Pick a suite with cases (for PlayReady,
          playready_v2 with a cases list), then start again.
        </div>
      )}

      {!active && log.length > 0 && (
        <ul className="trust-forge-log trust-forge-log-static">
          {log.slice(-6).map((line, i) => (
            <li key={`${i}-${line}`}>{line}</li>
          ))}
        </ul>
      )}

      {latestImprove && (
        <ImprovementCard
          title={
            latestImprove.vs_gen
              ? "How it improved vs previous generation"
              : "Baseline snapshot"
          }
          delta={latestImprove}
        />
      )}

      {genImproves.length > 1 && (
        <details className="trust-forge-improve-details" style={{ marginBottom: "0.85rem" }}>
          <summary>All generation comparisons ({genImproves.length})</summary>
          <div className="trust-forge-gen-list">
            {genImproves.map((g) => (
              <div key={g.gen} className="trust-forge-gen-row mono">
                <strong>Gen {g.gen - 1} → {g.gen}</strong>
                <span>{g.delta?.summary || `${g.fitness}%`}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {curve.length > 0 && (
        <div style={{ marginBottom: "0.85rem" }}>
          <div className="nav-label" style={{ marginBottom: 6 }}>
            Fitness curve
          </div>
          <div className="trust-forge-curve">
            {curve.map((f, i) => (
              <div key={i} className="trust-forge-curve-col" title={`gen ${i}: ${f}%`}>
                <div
                  className="trust-forge-curve-bar"
                  style={{
                    height: `${Math.max(8, Math.min(100, f))}%`,
                    background:
                      f >= (run?.threshold ?? threshold)
                        ? "var(--ok, #059669)"
                        : "var(--ink)",
                  }}
                />
                <span>{Math.round(f)}</span>
              </div>
            ))}
          </div>
          <div className="mono muted" style={{ fontSize: "0.72rem", marginTop: 6 }}>
            {curve.map((f) => `${f}%`).join(" → ")}
          </div>
        </div>
      )}

      {run && (run.stop_reason || run.error) && (
        <p className="muted" style={{ fontSize: "0.8rem", margin: 0, overflowWrap: "anywhere" }}>
          {run.stop_reason ? `Stopped: ${run.stop_reason}` : ""}
          {run.error ? `${run.stop_reason ? " · " : ""}${run.error}` : ""}
        </p>
      )}
    </div>
  );
}
