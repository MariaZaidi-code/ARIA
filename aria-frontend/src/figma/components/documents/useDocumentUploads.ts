import { useCallback, useEffect, useRef, useState } from "react";
import { listUploadJobs, uploadDocumentsBatch } from "../../../services/api";

export type UploadPhase =
  | "uploading"
  | "queued"
  | "validating"
  | "extracting"
  | "indexing"
  | "saving"
  | "ready"
  | "failed";

export interface UploadItem {
  key: string;
  name: string;
  size: number;
  phase: UploadPhase;
  /** 0–100: bytes sent fill the first 30%, server stages the rest. */
  progress: number;
  error?: string;
  documentId?: string;
  duplicate?: boolean;
  jobId?: string;
  file?: File;
}

export const ACCEPTED_EXTENSIONS = ["pdf", "csv", "xlsx", "docx"];
export const MAX_FILE_BYTES = 50 * 1024 * 1024;
const MAX_BATCH = 10;
const UPLOAD_SHARE = 30;
const TERMINAL: UploadPhase[] = ["ready", "failed"];

export const PHASE_LABEL: Record<UploadPhase, string> = {
  uploading: "Uploading",
  queued: "Waiting",
  validating: "Checking file",
  extracting: "Reading content",
  indexing: "Preparing for search",
  saving: "Saving",
  ready: "Ready",
  failed: "Failed",
};

/** Client-side check mirroring the server rules; the server re-validates. */
export function validateFile(file: File): string | null {
  const extension = file.name.toLowerCase().split(".").pop() || "";
  if (!ACCEPTED_EXTENSIONS.includes(extension)) return "Use a PDF, CSV, XLSX, or DOCX file.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_FILE_BYTES) return "This file is larger than 50 MB.";
  return null;
}

let keyCounter = 0;
const nextKey = () => `upload-${Date.now().toString(36)}-${(keyCounter += 1)}`;

/**
 * Multi-file upload queue with per-file progress.
 * `onSettled` fires once a batch has no running files, with the ids of
 * documents that became ready, so the page refreshes the library once.
 */
export function useDocumentUploads(onSettled: (readyIds: string[]) => void) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const mounted = useRef(true);
  const timers = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;

  useEffect(() => {
    mounted.current = true;
    const pending = timers.current;
    return () => {
      mounted.current = false;
      pending.forEach((timer) => clearTimeout(timer));
      pending.clear();
    };
  }, []);

  const patch = useCallback((keys: string[], update: (item: UploadItem) => Partial<UploadItem>) => {
    if (!mounted.current) return;
    setItems((current) => current.map((item) => (keys.includes(item.key) ? { ...item, ...update(item) } : item)));
  }, []);

  const later = useCallback((fn: () => void, ms: number) => {
    const timer = setTimeout(() => {
      timers.current.delete(timer);
      if (mounted.current) fn();
    }, ms);
    timers.current.add(timer);
  }, []);

  const poll = useCallback((batchId: string, byJob: Map<string, string>, started: number, failures = 0) => {
    void listUploadJobs(batchId)
      .then((response: any) => {
        const jobs: any[] = response?.data || [];
        let running = 0;
        const readyIds: string[] = [];
        for (const job of jobs) {
          const key = byJob.get(job.job_id);
          if (!key) continue;
          const phase = (job.stage || job.status) as UploadPhase;
          if (!TERMINAL.includes(phase)) running += 1;
          const documentId = job.document?.document_id;
          if (phase === "ready" && documentId) readyIds.push(documentId);
          patch([key], () => ({
            phase,
            progress: phase === "failed" ? 100 : UPLOAD_SHARE + Math.round((Number(job.progress) || 0) * (100 - UPLOAD_SHARE) / 100),
            error: job.error || undefined,
            documentId,
            duplicate: Boolean(job.duplicate),
          }));
        }
        if (running > 0) {
          // Quick polling while a fresh batch starts, then back off.
          later(() => poll(batchId, byJob, started, 0), Date.now() - started < 15000 ? 1500 : 4000);
        } else {
          onSettledRef.current(readyIds);
        }
      })
      .catch(() => {
        if (failures >= 4) {
          patch(Array.from(byJob.values()), (item) => TERMINAL.includes(item.phase) ? {} : {
            phase: "failed",
            error: "Lost track of this upload. Refresh the list to check whether it finished.",
          });
          onSettledRef.current([]);
          return;
        }
        later(() => poll(batchId, byJob, started, failures + 1), 2000 * (failures + 1));
      });
  }, [patch, later]);

  const sendBatch = useCallback(async (batch: UploadItem[]) => {
    const keys = batch.map((item) => item.key);
    try {
      const response: any = await uploadDocumentsBatch(batch.map((item) => item.file as File), {
        onUploadProgress: (fraction: number) =>
          patch(keys, () => ({ progress: Math.round(fraction * UPLOAD_SHARE) })),
      });
      const jobs: any[] = response?.data?.jobs || [];
      const byJob = new Map<string, string>();
      jobs.forEach((job, index) => {
        const key = keys[index];
        if (!key) return;
        byJob.set(job.job_id, key);
        const phase = (job.stage || job.status) as UploadPhase;
        patch([key], () => ({
          jobId: job.job_id,
          phase,
          progress: phase === "failed" ? 100 : UPLOAD_SHARE,
          error: job.error || undefined,
        }));
      });
      if (jobs.some((job) => !TERMINAL.includes((job.stage || job.status) as UploadPhase))) {
        poll(response.data.batch_id, byJob, Date.now());
      } else {
        onSettledRef.current([]);
      }
    } catch (error: any) {
      if (error?.name === "AbortError") return;
      patch(keys, () => ({ phase: "failed", progress: 100, error: error?.message || "Upload failed." }));
    }
  }, [patch, poll]);

  const addFiles = useCallback((fileList: FileList | File[] | null | undefined) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const created: UploadItem[] = files.map((file) => {
      const problem = validateFile(file);
      return {
        key: nextKey(),
        name: file.name,
        size: file.size,
        phase: problem ? "failed" : "uploading",
        progress: problem ? 100 : 0,
        error: problem || undefined,
        file: problem ? undefined : file,
      };
    });
    setItems((current) => [...created, ...current]);
    const valid = created.filter((item) => item.phase === "uploading");
    for (let start = 0; start < valid.length; start += MAX_BATCH) {
      void sendBatch(valid.slice(start, start + MAX_BATCH));
    }
  }, [sendBatch]);

  const retry = useCallback((key: string) => {
    const item = items.find((candidate) => candidate.key === key);
    if (!item?.file) return;
    const fresh: UploadItem = { ...item, phase: "uploading", progress: 0, error: undefined, jobId: undefined };
    setItems((current) => current.map((candidate) => (candidate.key === key ? fresh : candidate)));
    void sendBatch([fresh]);
  }, [items, sendBatch]);

  const dismiss = useCallback((key: string) => {
    setItems((current) => current.filter((item) => item.key !== key));
  }, []);

  const clearFinished = useCallback(() => {
    setItems((current) => current.filter((item) => !TERMINAL.includes(item.phase)));
  }, []);

  const busy = items.some((item) => !TERMINAL.includes(item.phase));
  return { items, addFiles, retry, dismiss, clearFinished, busy };
}
