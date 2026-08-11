import { Check, ChevronDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { RagDocument } from "../../api/types";

interface RagDocumentMultiSelectProps {
  label: string;
  documents: readonly RagDocument[];
  value: readonly string[];
  onChange: (value: string[]) => void;
  emptyLabel?: string;
}

/**
 * RAG document picker shared by search and evaluation flows. A real listbox keeps the
 * selected set compact in the form while still exposing each document as an independently
 * keyboard/focusable option; the outside-click handler only closes the menu and never mutates
 * the selection.
 */
export default function RagDocumentMultiSelect({
  label,
  documents,
  value,
  onChange,
  emptyLabel = "暂无可选资料",
}: RagDocumentMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();
  const selectedDocuments = documents.filter((document) => value.includes(document.id));

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const toggle = (documentId: string) => {
    onChange(
      value.includes(documentId)
        ? value.filter((currentId) => currentId !== documentId)
        : [...value, documentId],
    );
  };

  const summary = selectedDocuments.length
    ? selectedDocuments.length === 1
      ? selectedDocuments[0].title
      : `已选 ${selectedDocuments.length} 份资料`
    : "不限定资料（全库）";

  return (
    <div className="rag-document-multi-select" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="rag-document-multi-select-trigger"
        role="combobox"
        aria-label={label}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="rag-document-multi-select-summary">{summary}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {value.length > 0 ? (
        <button
          type="button"
          className="rag-document-multi-select-clear"
          aria-label={`清除${label}`}
          title={`清除${label}`}
          onClick={() => onChange([])}
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
      {open ? (
        <div
          id={listboxId}
          className="rag-document-multi-select-listbox"
          role="listbox"
          aria-label={label}
          aria-multiselectable="true"
        >
          {documents.length === 0 ? (
            <span className="rag-document-multi-select-empty">{emptyLabel}</span>
          ) : (
            documents.map((document) => {
              const selected = value.includes(document.id);
              return (
                <button
                  key={document.id}
                  type="button"
                  className="rag-document-multi-select-option"
                  role="option"
                  aria-selected={selected}
                  onClick={() => toggle(document.id)}
                >
                  <span className="rag-document-multi-select-option-title">{document.title}</span>
                  {selected ? <Check size={16} aria-hidden="true" /> : null}
                </button>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}
