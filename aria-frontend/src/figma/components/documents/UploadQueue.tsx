import { useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, RotateCcw, Upload, X } from "lucide-react";
import { PHASE_LABEL, type UploadItem } from "./useDocumentUploads";

const ACCEPT =
  ".pdf,.csv,.xlsx,.docx,application/pdf,text/csv," +
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet," +
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Header button that opens the file picker (multi-select). */
export function UploadButton({ onFiles, busy }: { onFiles: (files: FileList | null) => void; busy: boolean }) {
  return (
    <label className={`documents-upload ${busy ? "is-uploading" : ""}`}>
      <Upload size={15} />
      {busy ? "Uploading…" : "Upload documents"}
      <input
        type="file"
        multiple
        accept={ACCEPT}
        aria-label="Upload documents"
        onChange={(event) => {
          onFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </label>
  );
}

/** Whole-page drop target; shows an overlay while files are dragged over. */
export function useFileDrop(onFiles: (files: FileList | null) => void) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const hasFiles = (event: React.DragEvent) => Array.from(event.dataTransfer?.types || []).includes("Files");
  return {
    dragging,
    handlers: {
      onDragEnter: (event: React.DragEvent) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        depth.current += 1;
        setDragging(true);
      },
      onDragOver: (event: React.DragEvent) => {
        if (hasFiles(event)) event.preventDefault();
      },
      onDragLeave: (event: React.DragEvent) => {
        if (!hasFiles(event)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setDragging(false);
      },
      onDrop: (event: React.DragEvent) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        depth.current = 0;
        setDragging(false);
        onFiles(event.dataTransfer.files);
      },
    },
  };
}

export function DropOverlay() {
  return (
    <div className="doc-drop-overlay" aria-hidden="true">
      <Upload size={28} />
      <strong>Drop files to upload</strong>
      <span>PDF, CSV, XLSX or DOCX · up to 50 MB each</span>
    </div>
  );
}

export function UploadQueue({
  items,
  onRetry,
  onDismiss,
  onClear,
}: {
  items: UploadItem[];
  onRetry: (key: string) => void;
  onDismiss: (key: string) => void;
  onClear: () => void;
}) {
  if (!items.length) return null;
  const finished = items.filter((item) => item.phase === "ready" || item.phase === "failed").length;
  const failed = items.filter((item) => item.phase === "failed").length;
  return (
    <section className="doc-upload-queue" aria-label="Upload progress">
      <header>
        <strong>Uploads</strong>
        <span>
          {finished}/{items.length} done{failed ? ` · ${failed} failed` : ""}
        </span>
        {finished > 0 && (
          <button type="button" className="doc-link-button" onClick={onClear}>
            Clear finished
          </button>
        )}
      </header>
      <ul>
        {items.map((item) => {
          const running = item.phase !== "ready" && item.phase !== "failed";
          return (
            <li key={item.key} className={`doc-upload-item is-${item.phase}`} data-testid="upload-item">
              <span className="doc-upload-icon" aria-hidden="true">
                {item.phase === "ready" ? <CheckCircle2 size={16} />
                  : item.phase === "failed" ? <AlertCircle size={16} />
                  : <Loader2 size={16} className="doc-spin" />}
              </span>
              <div className="doc-upload-body">
                <div className="doc-upload-line">
                  <span className="doc-upload-name" title={item.name}>{item.name}</span>
                  <small>{formatSize(item.size)}</small>
                </div>
                <div
                  className="doc-progress"
                  role="progressbar"
                  aria-label={`${item.name} upload progress`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={item.progress}
                >
                  <span style={{ width: `${item.progress}%` }} />
                </div>
                <small className="doc-upload-status" aria-live="polite">
                  {item.phase === "failed"
                    ? item.error || "Upload failed."
                    : item.phase === "ready" && item.duplicate
                      ? "Already in your library"
                      : `${PHASE_LABEL[item.phase]}${running ? ` · ${item.progress}%` : ""}`}
                </small>
              </div>
              <div className="doc-upload-actions">
                {item.phase === "failed" && item.file && (
                  <button type="button" aria-label={`Retry ${item.name}`} onClick={() => onRetry(item.key)}>
                    <RotateCcw size={14} />
                  </button>
                )}
                {!running && (
                  <button type="button" aria-label={`Dismiss ${item.name}`} onClick={() => onDismiss(item.key)}>
                    <X size={14} />
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
