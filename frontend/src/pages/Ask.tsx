import { Link } from "react-router-dom";
import ChatConsole from "../components/ChatConsole";
import { useWorkspace } from "../state";

export default function Ask() {
  const { agentSettings, agentId, agents } = useWorkspace();

  if (!agents.length) {
    return (
      <div className="ask-focus ask-focus-empty">
        <h2>Create an agent first</h2>
        <p className="muted">Ask needs an agent with knowledge. Start from Agents, then come back here.</p>
        <Link className="btn btn-primary" to="/agent">
          Go to Agents
        </Link>
      </div>
    );
  }

  return (
    <div className="ask-focus">
      <ChatConsole
        key={agentId || "ask"}
        settings={agentSettings}
        showAgentPicker
        focusMode
      />
    </div>
  );
}
