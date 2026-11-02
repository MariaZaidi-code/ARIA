import { useEffect, useRef } from "react";

/** Accessible confirmation dialog (replaces window.confirm on this page). */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Delete",
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="doc-confirm-backdrop" onClick={onCancel}>
      <div
        className="doc-confirm"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="doc-confirm-title"
        aria-describedby="doc-confirm-message"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="doc-confirm-title">{title}</h2>
        <p id="doc-confirm-message">{message}</p>
        <div className="doc-confirm-actions">
          <button ref={cancelRef} type="button" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="danger-action" onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
