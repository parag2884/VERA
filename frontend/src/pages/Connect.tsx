import KnowledgeConnectPanel from "../components/KnowledgeConnectPanel";
import { useWorkspace } from "../state";

export default function Connect() {
  const { currentAgent, refreshAgents } = useWorkspace();

  return (
    <div>
      <div className="page-kicker">Knowledge in</div>
      <h2 className="section-title">Connect knowledge</h2>
      <p className="section-sub">
        Attaches to the agent selected in <strong>Working on</strong>
        {currentAgent ? (
          <>
            {" "}
            — currently <strong>{currentAgent.name}</strong>
          </>
        ) : null}
        . One agent · one graph. Point at a source — we CleanStack, weave evidence, and answer with
        proof.
      </p>

      <KnowledgeConnectPanel onIngestComplete={() => void refreshAgents()} />
    </div>
  );
}
