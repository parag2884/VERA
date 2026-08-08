const LEVELS = [
  { level: "L4", title: "Cited Answer", note: "Only when every claim is proved" },
  { level: "L3", title: "Evidence Quotes", note: "Source spans along the trail" },
  { level: "L2", title: "Trust Trail", note: "Evidence-bound graph path" },
  { level: "L1", title: "Knowledge Graph", note: "Structure before similarity" },
];

export default function TrustPyramid() {
  return (
    <div className="pyramid">
      {LEVELS.map((l) => (
        <div className="pyramid-level" key={l.level}>
          <strong>{l.level}</strong>
          <div>
            <div className="title">{l.title}</div>
            <div className="note">{l.note}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
