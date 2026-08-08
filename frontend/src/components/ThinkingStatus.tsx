import { useEffect, useState } from "react";

/** Progressive status copy while Ask is in flight (client-side; API is not streamed). */
export const THINKING_STEPS = [
  "Reading your question…",
  "Understanding what you’re asking…",
  "Searching the knowledge graph…",
  "Gathering evidence quotes…",
  "Checking the Trust Trail…",
  "Preparing a verified answer…",
] as const;

type Props = {
  active: boolean;
  /** Milliseconds between step advances */
  intervalMs?: number;
};

export default function ThinkingStatus({ active, intervalMs = 1400 }: Props) {
  const [step, setStep] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!active) {
      setStep(0);
      setVisible(false);
      return;
    }
    setStep(0);
    setVisible(true);
    const id = window.setInterval(() => {
      setStep((s) => Math.min(s + 1, THINKING_STEPS.length - 1));
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [active, intervalMs]);

  if (!active || !visible) return null;

  return (
    <div className="bubble assistant thinking-bubble" aria-live="polite" aria-busy="true">
      <div className="thinking-row">
        <span className="thinking-dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
        <div className="thinking-copy">
          <strong>Working</strong>
          <span key={step} className="thinking-step">
            {THINKING_STEPS[step]}
          </span>
        </div>
      </div>
      <ol className="thinking-trail">
        {THINKING_STEPS.map((label, i) => (
          <li key={label} className={i < step ? "done" : i === step ? "current" : ""}>
            {label.replace(/…$/, "")}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function shortThinkingLabel(stepIndex: number): string {
  const labels = ["Reading…", "Understanding…", "Searching…", "Gathering…", "Trail…", "Verifying…"];
  return labels[Math.min(stepIndex, labels.length - 1)] || "Working…";
}
