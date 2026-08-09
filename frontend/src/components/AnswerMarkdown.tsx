/** Lightweight markdown renderer for VERA answers (no extra dependency). */

import type { ReactNode } from "react";

type Props = {
  text: string;
  className?: string;
  /** Soft-close unfinished ** / ` while tokens are still arriving. */
  live?: boolean;
};

/** Soft-close unfinished markers so live streaming still looks formatted. */
function softCloseMarkdown(src: string): string {
  let t = src;
  if (((t.match(/\*\*/g) || []).length) % 2 === 1) t += "**";
  const withoutBold = t.replace(/\*\*/g, "");
  if (((withoutBold.match(/`/g) || []).length) % 2 === 1) t += "`";
  return t;
}

function inlineFormat(text: string): ReactNode[] {
  // Split on **bold**, *italic*, `code` — order matters
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.filter(Boolean).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={i}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2 && !part.startsWith("**")) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    return <span key={i}>{part}</span>;
  });
}

function isBullet(line: string): boolean {
  return /^\s*[-*•]\s+/.test(line);
}

function isNumbered(line: string): boolean {
  return /^\s*\d+[.)]\s+/.test(line);
}

function stripBullet(line: string): string {
  return line.replace(/^\s*[-*•]\s+/, "");
}

function stripNumbered(line: string): string {
  return line.replace(/^\s*\d+[.)]\s+/, "");
}

/** Plain "In simple terms:" (with or without >) → green callout */
function isSimpleTermsLine(line: string): boolean {
  return /^\s*(?:>\s*)?(?:\*\*)?In simple terms:?\**/i.test(line.trim());
}

export function AnswerMarkdown({ text, className, live }: Props) {
  let raw = (text || "").replace(/\r\n/g, "\n");
  if (live) {
    raw = softCloseMarkdown(raw).replace(/^\s+/, "");
  } else {
    raw = raw.trim();
  }
  if (!raw) return null;

  const lines = raw.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    // Headings
    const h = /^(#{1,3})\s+(.+)$/.exec(line.trim());
    if (h) {
      const level = h[1].length;
      const content = inlineFormat(h[2].trim());
      if (level === 1) blocks.push(<h3 key={key++} className="ans-h">{content}</h3>);
      else if (level === 2) blocks.push(<h3 key={key++} className="ans-h">{content}</h3>);
      else blocks.push(<h4 key={key++} className="ans-h">{content}</h4>);
      i += 1;
      continue;
    }

    // Green callout: markdown > … OR plain "In simple terms:" paragraphs
    if (/^\s*>\s?/.test(line) || isSimpleTermsLine(line)) {
      const quoteLines: string[] = [];
      if (/^\s*>\s?/.test(line)) {
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
          i += 1;
        }
      } else {
        quoteLines.push(line.trim());
        i += 1;
        while (
          i < lines.length &&
          lines[i].trim() &&
          !isBullet(lines[i]) &&
          !isNumbered(lines[i]) &&
          !/^(#{1,3})\s+/.test(lines[i].trim()) &&
          !/^\s*>\s?/.test(lines[i]) &&
          !isSimpleTermsLine(lines[i])
        ) {
          quoteLines[0] = `${quoteLines[0]} ${lines[i].trim()}`;
          i += 1;
        }
      }
      blocks.push(
        <blockquote key={key++} className="ans-callout">
          {quoteLines.map((ql, qi) => (
            <p key={qi}>{inlineFormat(ql)}</p>
          ))}
        </blockquote>
      );
      continue;
    }

    // Bullet list
    if (isBullet(line)) {
      const items: string[] = [];
      while (i < lines.length && isBullet(lines[i])) {
        const item = stripBullet(lines[i]).trim();
        if (item) items.push(item);
        i += 1;
      }
      if (items.length) {
        blocks.push(
          <ul key={key++} className="ans-list">
            {items.map((item, ii) => (
              <li key={ii}>{inlineFormat(item)}</li>
            ))}
          </ul>
        );
      }
      continue;
    }

    // Numbered list
    if (isNumbered(line)) {
      const items: string[] = [];
      while (i < lines.length && isNumbered(lines[i])) {
        const item = stripNumbered(lines[i]).trim();
        if (item) items.push(item);
        i += 1;
      }
      if (items.length) {
        blocks.push(
          <ol key={key++} className="ans-list ans-ol">
            {items.map((item, ii) => (
              <li key={ii}>{inlineFormat(item)}</li>
            ))}
          </ol>
        );
      }
      continue;
    }

    // Paragraph (consume until blank or special)
    const para: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,3})\s+/.test(lines[i].trim()) &&
      !/^\s*>\s?/.test(lines[i]) &&
      !isBullet(lines[i]) &&
      !isNumbered(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p key={key++} className="ans-p">
        {inlineFormat(para.join(" "))}
      </p>
    );
  }

  return <div className={`answer-md ${className || ""}`.trim()}>{blocks}</div>;
}
