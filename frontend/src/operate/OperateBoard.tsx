import { Link } from "react-router-dom";

type Rec = {
  title?: string;
  expected_debt_delta?: number | null;
  coverage_gain?: number;
  driver?: string;
  policy?: boolean;
};

type Operate = {
  status?: string;
  risk?: string;
  debt?: number;
  coverage?: number;
  quiet?: boolean;
  week?: { text?: string } | null;
  recommended?: Rec[];
  drift?: Array<{ metric?: string; note?: string }>;
  sources?: { disappeared_count?: number };
  guardrail?: string;
};

export default function OperateBoard({
  operate,
  connectCta,
  onInternals,
}: {
  operate?: Operate | null;
  connectCta?: boolean;
  onInternals: () => void;
}) {
  const quiet = Boolean(operate?.quiet);
  const recs = operate?.recommended || [];
  const top = recs[0];

  return (
    <div className="panel operate-board">
      <div className="nav-label">Knowledge operations</div>
      <h3 className="care-headline">
        {quiet
          ? "System healthy. No action required."
          : top?.title
            ? `Action needed: ${top.title}`
            : `Needs attention (${operate?.status || "Watch"})`}
      </h3>
      {quiet && operate?.week?.text ? (
        <p className="operate-kpis">This week · {operate.week.text}</p>
      ) : null}
      {!quiet && (
        <>
          <p className="operate-kpis">
            Risk {operate?.risk ?? "—"}
            {" · "}
            Debt {operate?.debt ?? "—"}%
            {" · "}
            Coverage {operate?.coverage ?? "—"}%
          </p>
          {recs.length > 0 && (
            <ol className="operate-recs">
              {recs.slice(0, 3).map((r, i) => (
                <li key={`${r.title}-${i}`}>
                  <strong>{r.title}</strong>
                  {r.policy ? (
                    <span className="muted"> · Govern — a person must decide</span>
                  ) : (
                    <span className="muted"> · Observe / maintain</span>
                  )}
                </li>
              ))}
            </ol>
          )}
          {(operate?.drift || []).slice(0, 2).map((d) => (
            <p key={d.metric} className="muted" style={{ fontSize: "0.85rem" }}>
              {d.note}
            </p>
          ))}
          {(operate?.sources?.disappeared_count || 0) > 0 && (
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              {operate?.sources?.disappeared_count} source URLs missing vs last snapshot.
            </p>
          )}
        </>
      )}
      <div className="kos-toolbar" style={{ marginTop: "0.9rem" }}>
        {connectCta ? (
          <Link className="btn btn-primary" to="/connect" style={{ textDecoration: "none" }}>
            Add knowledge
          </Link>
        ) : (
          <Link className="btn btn-primary" to="/ask" style={{ textDecoration: "none" }}>
            Ask
          </Link>
        )}
        <button type="button" className="btn btn-ghost" onClick={onInternals}>
          Internals
        </button>
      </div>
    </div>
  );
}
