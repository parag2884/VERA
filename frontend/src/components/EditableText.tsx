import { useEffect, useRef, useState, type RefObject } from "react";

type Props = {
  value: string;
  onSave: (next: string) => void | Promise<void>;
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  as?: "h2" | "h3" | "strong" | "span" | "div";
  multiline?: boolean;
  maxLength?: number;
};

export default function EditableText({
  value,
  onSave,
  className = "",
  inputClassName = "",
  placeholder = "Click to edit",
  as = "span",
  multiline = false,
  maxLength = 80,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const Tag = as;

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (editing) ref.current?.focus();
  }, [editing]);

  async function commit() {
    const next = draft.trim();
    if (!next || next === value) {
      setDraft(value);
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    if (multiline) {
      return (
        <textarea
          ref={ref as RefObject<HTMLTextAreaElement>}
          className={`editable-input ${inputClassName}`}
          value={draft}
          maxLength={maxLength}
          rows={2}
          disabled={saving}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setDraft(value);
              setEditing(false);
            }
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void commit();
            }
          }}
        />
      );
    }
    return (
      <input
        ref={ref as RefObject<HTMLInputElement>}
        className={`editable-input ${inputClassName}`}
        value={draft}
        maxLength={maxLength}
        disabled={saving}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
          if (e.key === "Enter") {
            e.preventDefault();
            void commit();
          }
        }}
      />
    );
  }

  return (
    <Tag
      className={`editable-text ${className}`}
      role="button"
      tabIndex={0}
      title="Click to rename"
      onClick={() => setEditing(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setEditing(true);
        }
      }}
    >
      {value || placeholder}
      <span className="editable-hint" aria-hidden>
        edit
      </span>
    </Tag>
  );
}
