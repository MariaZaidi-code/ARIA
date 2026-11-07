import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Eye,
  File,
  FileSpreadsheet,
  FileText,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import {
  askDocuments,
  deleteDocument,
  deleteDocumentConversation,
  documentSourcesView,
  getDocument,
  getDocumentConversation,
  getDocumentDashboard,
  getDocumentOverview,
  listDocumentConversations,
  listDocuments,
  retryDocument,
  searchDocuments,
} from "../../services/api";
import { useToast } from "../../components/Toast";
import { ChatSessions, type ChatSummary } from "../components/documents/ChatSessions";
import { ConfirmDialog } from "../components/documents/ConfirmDialog";
import { DocumentAnswer } from "../components/documents/DocumentAnswer";
import { DocumentAnswerChart } from "../components/documents/DocumentAnswerChart";
import { DropOverlay, UploadButton, UploadQueue, useFileDrop } from "../components/documents/UploadQueue";
import { useDocumentUploads } from "../components/documents/useDocumentUploads";
import "./Documents.css";
import "../components/documents/documents-ui.css";

type LibraryFilter = "all" | "pdf" | "spreadsheets" | "word" | "7days" | "30days" | `tag:${string}`;

interface PendingConfirm {
  title: string;
  message: string;
  confirmLabel?: string;
  action: () => Promise<void>;
}

const SPREADSHEET_EXTENSIONS = new Set(["csv", "xls", "xlsx"]);
const WORD_EXTENSIONS = new Set(["doc", "docx", "rtf"]);

function extensionOf(document: any) {
  return String(document?.name || document?.original_name || "").split(".").pop()?.toLowerCase() || "";
}

function formatSize(bytes?: number) {
  const size = Number(bytes) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function shortNumber(value?: number) {
  const number = Number(value) || 0;
  return number >= 1000 ? `${(number / 1000).toFixed(1)}k` : number.toLocaleString();
}

/** "1 page", "3 pages", "1.2k sections" — count with the right singular/plural word. */
function countLabel(value: number | undefined, singular: string, plural = `${singular}s`) {
  const number = Number(value) || 0;
  return `${shortNumber(number)} ${number === 1 ? singular : plural}`;
}

function fileIcon(extension: string) {
  if (SPREADSHEET_EXTENSIONS.has(extension)) return FileSpreadsheet;
  if (WORD_EXTENSIONS.has(extension) || extension === "pdf") return FileText;
  return File;
}

function documentKind(document: any) {
  const extension = extensionOf(document);
  if (SPREADSHEET_EXTENSIONS.has(extension)) return "Spreadsheet";
  if (WORD_EXTENSIONS.has(extension)) return "Word document";
  if (extension === "pdf") return "PDF";
  return extension ? extension.toUpperCase() : "Document";
}

/** "p. 3", "rows 1–25", … — falls back to the page number for older payloads. */
function locationText(item: any) {
  if (item?.location_label) return String(item.location_label);
  return item?.page_number ? `p. ${item.page_number}` : "";
}

function StatusBadge({ status }: { status?: string }) {
  const value = status || "ready";
  return <span className={`doc-status doc-status-${value}`}>{value}</span>;
}

function LibrarySkeleton() {
  return (
    <div className="documents-file-list" aria-label="Loading documents" aria-busy="true">
      {Array.from({ length: 4 }, (_, index) => (
        <div className="doc-skeleton-row" key={index}>
          <span className="doc-skeleton" />
          <div><span className="doc-skeleton" /><span className="doc-skeleton" /></div>
        </div>
      ))}
    </div>
  );
}

function turnFromResponse(question: string, data: any) {
  return {
    question,
    answer: data?.answer || "I couldn't find a clear answer in the available document text.",
    passages: data?.passages || [],
    citations: data?.citations || [],
    sources: data?.sources || [],
    visualization: data?.visualization || null,
    answerMode: data?.answer_mode || "ai",
  };
}

export default function Documents() {
  const [documents, setDocuments] = useState<any[]>([]);
  const documentsRef = useRef(documents);
  documentsRef.current = documents;
  const [overview, setOverview] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [page, setPage] = useState(0);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [previewDoc, setPreviewDoc] = useState<any | null>(null);
  const [previewChunks, setPreviewChunks] = useState<any[]>([]);
  const [previewMetrics, setPreviewMetrics] = useState<any[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [previewPage, setPreviewPage] = useState<number | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<any[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [chatsLoading, setChatsLoading] = useState(false);
  const [chatsError, setChatsError] = useState("");
  const [openingChat, setOpeningChat] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const chatInputRef = useRef<HTMLInputElement>(null);
  const [recentQueries, setRecentQueries] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("aria_doc_recent_queries") || "[]");
      return Array.isArray(stored) ? stored : [];
    } catch {
      return [];
    }
  });
  const [compareDocs, setCompareDocs] = useState<any[] | null>(null);
  const [compareChunks, setCompareChunks] = useState<any[][]>([]);
  const [compareLoading, setCompareLoading] = useState(false);
  const [menuDocId, setMenuDocId] = useState<string | null>(null);
  const { error: toastError, success: toastSuccess, info: toastInfo } = useToast() as any;

  const fetchAll = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const response: any = await listDocuments();
      const docs: any[] = response.success ? response.data || [] : [];
      setDocuments(docs);
      setActiveDocId((current) => current && docs.some((doc) => doc.id === current) ? current : null);
      setSelected((current) => new Set([...current].filter((id) => docs.some((doc) => doc.id === id))));

      try {
        const stats: any = await getDocumentOverview();
        if (stats.success) setOverview(stats.data || {});
      } catch {
        toastError("Document totals could not be refreshed");
      }

      for (const doc of docs) {
        if (!doc?.id || (Number(doc.summary_version) || 0) >= 2) continue;
        void (async () => {
          try {
            const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/summary`, {
              method: "POST",
              credentials: "include",
            });
            if (!response.ok) throw new Error("The summary service returned an error");
            const summary = await response.json();
            if (!summary?.ok || !summary.summary || Number(summary.summary_version) < 2) {
              throw new Error("The summary service did not return a readable summary");
            }
            setDocuments((current) => current.map((item) =>
              item.id === doc.id ? { ...item, summary: summary.summary, summary_version: summary.summary_version } : item,
            ));
            setPreviewDoc((current: any) =>
              current?.id === doc.id ? { ...current, summary: summary.summary, summary_version: summary.summary_version } : current,
            );
          } catch {
            toastError(`Could not generate a readable summary for ${doc.name || "this document"}`);
          }
        })();
      }
    } catch (error: any) {
      setLoadError(error?.message || "Failed to load documents");
      toastError("Failed to load documents");
    } finally {
      setLoading(false);
    }
  };

  const uploads = useDocumentUploads((readyIds) => {
    void fetchAll();
    if (readyIds.length === 1) setActiveDocId(readyIds[0]);
    if (readyIds.length) toastSuccess(`${readyIds.length} document${readyIds.length === 1 ? "" : "s"} ready`);
  });
  const drop = useFileDrop(uploads.addFiles);

  const loadChats = useCallback(async () => {
    setChatsLoading(true);
    setChatsError("");
    try {
      const response: any = await listDocumentConversations(30);
      setChats(response?.data || []);
    } catch (error: any) {
      setChatsError(error?.message || "Saved chats couldn't be loaded.");
    } finally {
      setChatsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAll();
    void loadChats();
  }, []);

  useEffect(() => {
    if (!activeDocId) {
      setPreviewDoc(null);
      setPreviewChunks([]);
      setPreviewMetrics([]);
      return;
    }
    let cancelled = false;
    const selectedDoc = documentsRef.current.find((doc) => doc.id === activeDocId);
    setPreviewDoc(selectedDoc || null);
    setPreviewChunks([]);
    setPreviewMetrics([]);
    setPreviewError("");
    setPreviewLoading(true);

    void (async () => {
      const detailPromise = getDocument(activeDocId);
      const chunksPromise = fetch(`/api/documents/${encodeURIComponent(activeDocId)}/chunks`, {
        credentials: "include",
      }).then(async (response) => {
        if (!response.ok) throw new Error("Could not load extracted text");
        return response.json();
      });
      const metricsPromise = getDocumentDashboard(activeDocId);
      const [detail, chunks, metrics] = await Promise.allSettled([detailPromise, chunksPromise, metricsPromise]);
      if (cancelled) return;

      if (detail.status === "fulfilled" && detail.value?.data) {
        setPreviewDoc((current: any) => ({
          ...selectedDoc,
          ...current,
          summary: detail.value.data.summary || current?.summary || selectedDoc?.summary,
          summary_version: detail.value.data.summary_version || current?.summary_version || selectedDoc?.summary_version,
          text_chars: detail.value.data.text_chars || current?.text_chars,
        }));
      } else if (detail.status === "rejected") {
        setPreviewError(detail.reason?.message || "Could not load document details");
      }
      if (chunks.status === "fulfilled" && chunks.value?.ok) {
        setPreviewChunks(chunks.value.chunks || []);
      } else if (chunks.status === "rejected") {
        setPreviewError(chunks.reason?.message || "Could not load document text");
      }
      if (metrics.status === "fulfilled") setPreviewMetrics(metrics.value?.data?.metrics || []);
      setPreviewLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [activeDocId]);

  useEffect(() => {
    if (!activeDocId) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pendingConfirm) setActiveDocId(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [activeDocId, pendingConfirm]);

  const toggleSelected = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onSearch = async () => {
    const search = query.trim();
    if (!search) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      const response: any = await searchDocuments(search, undefined, 20);
      if (response.success) setResults(response.data || []);
      const next = [search, ...recentQueries.filter((item) => item !== search)].slice(0, 6);
      setRecentQueries(next);
      try {
        localStorage.setItem("aria_doc_recent_queries", JSON.stringify(next));
      } catch {
        // Recent searches are a convenience and need not block document search.
      }
    } catch (error: any) {
      toastError(error?.message || "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const clearSearch = () => {
    setQuery("");
    setResults(null);
  };

  const openPreview = (doc: any, citedPage?: number) => {
    setActiveDocId(doc.id);
    setPreviewPage(citedPage ?? null);
  };

  const onChat = async (question = chatInput) => {
    const prompt = question.trim();
    if (!prompt || chatLoading) return;
    setChatLoading(true);
    try {
      // Always explicit: selected documents, or [] for "all documents". The
      // backend saves this scope on the chat so reopening it restores it.
      const ids = selected.size > 0 ? Array.from(selected) : [];
      const response: any = await askDocuments(prompt, ids, conversationId);
      if (!response?.success) throw new Error(response?.message || "The document assistant could not answer");
      const isNewChat = !conversationId;
      if (response?.data?.conversation_id) setConversationId(response.data.conversation_id);
      const turn = turnFromResponse(prompt, response?.data);
      setChatInput("");
      setChatMessages((current) => [...current, turn]);
      if (!turn.passages.length) toastInfo("No matching passages found. Try a different question.");
      if (isNewChat) void loadChats();
    } catch (error: any) {
      const errorMessage = error?.message || "The document assistant couldn't reach the document service. Try again.";
      setChatMessages((current) => [...current, {
        question: prompt,
        answer: errorMessage,
        passages: [],
        citations: [],
        error: true,
      }]);
      toastError(error?.message || "Could not ask the document assistant");
    } finally {
      setChatLoading(false);
    }
  };

  const onNewChat = () => {
    setConversationId(null);
    setChatMessages([]);
    setChatInput("");
    chatInputRef.current?.focus();
  };

  const onOpenChat = async (id: string) => {
    if (id === conversationId) return;
    setOpeningChat(true);
    try {
      const response: any = await getDocumentConversation(id);
      const conversation = response?.data;
      if (!conversation) throw new Error("This chat is no longer available.");
      const turns: any[] = [];
      let question = "";
      for (const message of conversation.messages || []) {
        if (message.role === "user") {
          question = message.content;
        } else if (message.role === "assistant") {
          turns.push(turnFromResponse(question, { answer: message.content, ...documentSourcesView(message.sources), sources: message.sources }));
          question = "";
        }
      }
      setConversationId(id);
      setChatMessages(turns);
      const scope: string[] = (conversation.scope_document_ids || [])
        .filter((docId: string) => documentsRef.current.some((doc) => doc.id === docId));
      setSelected(new Set(scope));
    } catch (error: any) {
      toastError(error?.message || "Could not open that chat");
    } finally {
      setOpeningChat(false);
    }
  };

  const onDeleteChat = (chat: ChatSummary) => {
    setPendingConfirm({
      title: "Delete this chat?",
      message: `“${chat.title || "Untitled chat"}” and its answers will be removed. Your documents are not affected.`,
      action: async () => {
        await deleteDocumentConversation(chat.conversation_id);
        if (chat.conversation_id === conversationId) onNewChat();
        setChats((current) => current.filter((item) => item.conversation_id !== chat.conversation_id));
        toastSuccess("Chat deleted");
      },
    });
  };

  const runConfirm = async () => {
    if (!pendingConfirm) return;
    setConfirmBusy(true);
    try {
      await pendingConfirm.action();
      setPendingConfirm(null);
    } catch (error: any) {
      toastError(error?.message || "That action failed. Please try again.");
    } finally {
      setConfirmBusy(false);
    }
  };

  const onDelete = (doc: any) => {
    setMenuDocId(null);
    setPendingConfirm({
      title: "Delete this document?",
      message: `“${doc.name || "This document"}” will be removed from search and chat. This cannot be undone.`,
      action: async () => {
        setDeleting(doc.id);
        try {
          await deleteDocument(doc.id);
          setSelected((current) => {
            const next = new Set(current);
            next.delete(doc.id);
            return next;
          });
          toastSuccess("Document deleted");
          await fetchAll();
        } finally {
          setDeleting(null);
        }
      },
    });
  };

  const onDeleteSelected = () => {
    const ids = Array.from(selected);
    setPendingConfirm({
      title: `Delete ${ids.length} document${ids.length === 1 ? "" : "s"}?`,
      message: "The selected documents will be removed from search and chat. This cannot be undone.",
      action: async () => {
        const outcomes = await Promise.allSettled(ids.map((id) => deleteDocument(id)));
        const failed = outcomes.filter((outcome) => outcome.status === "rejected").length;
        setSelected(new Set());
        if (failed) toastError(`${failed} document${failed === 1 ? "" : "s"} couldn't be deleted. Try again.`);
        else toastSuccess("Selected documents deleted");
        await fetchAll();
      },
    });
  };

  const onRetry = async (doc: any, rechunk = false) => {
    setRetrying(doc.id);
    try {
      await retryDocument(doc.id, { rechunk });
      toastSuccess(rechunk ? "Tables re-extracted" : "Document re-indexed");
      await fetchAll();
    } catch (error: any) {
      toastError(error?.message || "Retry failed");
    } finally {
      setRetrying(null);
    }
  };

  const onRetrySelected = async () => {
    const retryable = documents.filter((doc) => selected.has(doc.id) && ["failed", "partial"].includes(doc.status));
    const outcomes = await Promise.allSettled(retryable.map((doc) => retryDocument(doc.id)));
    outcomes.forEach((outcome, index) => {
      if (outcome.status === "rejected") toastError(`Could not retry ${retryable[index].name || "a selected document"}`);
    });
    if (retryable.length) {
      toastSuccess("Selected documents were refreshed and are ready to search");
      await fetchAll();
    }
  };

  const onAskDocuments = (documentIds: string[]) => {
    setMenuDocId(null);
    setSelected(new Set(documentIds));
    chatInputRef.current?.focus();
    toastInfo(`Ask the assistant about ${documentIds.length} selected document${documentIds.length === 1 ? "" : "s"}.`);
  };

  const onCompare = async () => {
    const docs = documents.filter((doc) => selected.has(doc.id)).slice(0, 4);
    if (docs.length < 2) return;
    setCompareDocs(docs);
    setCompareChunks([]);
    setCompareLoading(true);
    try {
      const chunks = await Promise.all(docs.map(async (doc) => {
        const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/chunks`, { credentials: "include" });
        if (!response.ok) throw new Error("Could not load comparison");
        return response.json();
      }));
      setCompareChunks(chunks.map((item) => item?.chunks || []));
    } catch (error: any) {
      toastError(error?.message || "Could not load comparison");
    } finally {
      setCompareLoading(false);
    }
  };

  const onExport = async (doc: any) => {
    try {
      const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/export`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) throw new Error("Export failed");
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${doc.name || "document"}.html`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error: any) {
      toastError(error?.message || "Export failed");
    }
  };

  const onDataset = async (doc: any) => {
    try {
      const response = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/to-dataset`, {
        method: "POST",
        credentials: "include",
      });
      const data = await response.json();
      if (!response.ok || !data?.ok) throw new Error(data?.detail || "No tables found");
      toastSuccess(`Dataset ready: ${data.tables?.length || 0} tables`);
    } catch (error: any) {
      toastError(error?.message || "Could not create a dataset");
    }
  };

  const openCitedSource = (message: any, sourceId: string) => {
    const source = (message.sources || []).find((item: any) => String(item.source_id) === sourceId);
    const doc = source && documents.find((item) => item.id === source.document_id);
    if (doc) openPreview(doc, source.page);
  };

  const tags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const doc of documents) {
      const values = [...(doc.tags || []), ...(doc.collection ? [doc.collection] : [])];
      for (const value of new Set(values)) counts.set(value, (counts.get(value) || 0) + 1);
    }
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [documents]);

  const filteredDocuments = useMemo(() => {
    const search = query.trim().toLocaleLowerCase();
    const cutoff = filter === "7days" || filter === "30days"
      ? Date.now() - (filter === "7days" ? 7 : 30) * 24 * 60 * 60 * 1000
      : null;
    return documents.filter((doc) => {
      const ext = extensionOf(doc);
      if (filter === "pdf" && ext !== "pdf") return false;
      if (filter === "spreadsheets" && !SPREADSHEET_EXTENSIONS.has(ext)) return false;
      if (filter === "word" && !WORD_EXTENSIONS.has(ext)) return false;
      if (filter.startsWith("tag:")) {
        const label = filter.slice(4);
        if (!(doc.tags || []).includes(label) && doc.collection !== label) return false;
      }
      if (cutoff && (!doc.created_at || new Date(doc.created_at).getTime() < cutoff)) return false;
      if (search) {
        const haystack = [doc.name, doc.collection, ...(doc.tags || [])].join(" ").toLocaleLowerCase();
        if (!haystack.includes(search)) return false;
      }
      return true;
    });
  }, [documents, filter, query]);

  const pageSize = 8;
  const pageCount = Math.max(1, Math.ceil(filteredDocuments.length / pageSize));
  const pageDocuments = filteredDocuments.slice(page * pageSize, (page + 1) * pageSize);
  const activeDocument = activeDocId ? documents.find((doc) => doc.id === activeDocId) || previewDoc : null;
  const selectedAll = filteredDocuments.length > 0 && filteredDocuments.every((doc) => selected.has(doc.id));
  const prompts = activeDocument
    ? [`What are the key takeaways from ${activeDocument.name || "this document"}?`, `Summarize ${activeDocument.name || "this document"}.`, "What actions are recommended?"]
    : selected.size >= 2
      ? ["Compare the selected documents.", "What do these documents agree and disagree on?", "Which figures differ between them?"]
      : ["What are the key takeaways in my documents?", "Summarize the latest report.", "What actions should I prioritize?"];

  return (
    <div className={`documents-page ${drop.dragging ? "is-dragging" : ""}`} {...drop.handlers}>
      {drop.dragging && <DropOverlay />}
      <header className="documents-header">
        <div>
          <div className="documents-eyebrow"><FileText size={14} /> Document workspace</div>
          <h1>Documents</h1>
          <p>Upload PDF, CSV, XLSX spreadsheet, and DOCX Word documents to search and explore their contents. Drop several files at once.</p>
        </div>
        <UploadButton onFiles={uploads.addFiles} busy={uploads.busy} />
      </header>

      <UploadQueue items={uploads.items} onRetry={uploads.retry} onDismiss={uploads.dismiss} onClear={uploads.clearFinished} />

      <label className="documents-global-search">
        <Search size={16} />
        <input
          value={query}
          onChange={(event) => { setQuery(event.target.value); setPage(0); }}
          onKeyDown={(event) => { if (event.key === "Enter") void onSearch(); }}
          placeholder="Search across your data, documents, and insights…"
          aria-label="Search documents"
        />
        {searching && <span className="documents-search-loading">Searching</span>}
        {query && <button type="button" aria-label="Clear search" onClick={clearSearch}><X size={14} /></button>}
        <button type="button" className="documents-search-submit" aria-label="Search document contents" onClick={() => void onSearch()}>
          <Search size={14} />
        </button>
      </label>

      <section className="documents-stats" aria-label="Document library statistics">
        <article className="documents-stat">
          <span className="documents-stat-icon stat-blue"><FileText size={16} /></span>
          <span><small>Total documents</small><strong>{Number(overview.total_documents ?? documents.length).toLocaleString()}</strong></span>
        </article>
        <article className="documents-stat">
          <span className="documents-stat-icon stat-purple"><Database size={16} /></span>
          <span><small>Storage used</small><strong>{formatSize(overview.storage_bytes)}</strong></span>
        </article>
        <article className="documents-stat">
          <span className="documents-stat-icon stat-green"><Sparkles size={16} /></span>
          <span><small>Sections read</small><strong>{shortNumber(overview.elements_extracted)}</strong></span>
        </article>
        <article className="documents-stat">
          <span className="documents-stat-icon stat-amber"><Clock3 size={16} /></span>
          <span><small>Last uploaded</small><strong>{formatDate(overview.last_uploaded_at)}</strong></span>
        </article>
      </section>

      <section className="documents-workspace">
        <aside className="documents-filters" aria-label="Document filters">
          <h2>Documents</h2>
          <button className={filter === "all" ? "active" : ""} onClick={() => { setFilter("all"); setPage(0); }}>
            <FileText size={14} /><span>All documents</span><b>{documents.length}</b>
          </button>
          <button className={filter === "pdf" ? "active" : ""} onClick={() => { setFilter("pdf"); setPage(0); }}>
            <FileText size={14} /><span>PDFs</span><b>{overview.formats?.pdf ?? documents.filter((doc) => extensionOf(doc) === "pdf").length}</b>
          </button>
          <button className={filter === "spreadsheets" ? "active" : ""} onClick={() => { setFilter("spreadsheets"); setPage(0); }}>
            <FileSpreadsheet size={14} /><span>Spreadsheets</span><b>{documents.filter((doc) => SPREADSHEET_EXTENSIONS.has(extensionOf(doc))).length}</b>
          </button>
          <button className={filter === "word" ? "active" : ""} onClick={() => { setFilter("word"); setPage(0); }}>
            <File size={14} /><span>Word documents</span><b>{documents.filter((doc) => WORD_EXTENSIONS.has(extensionOf(doc))).length}</b>
          </button>
          <div className="documents-filter-separator" />
          <h3>Recent</h3>
          <button className={filter === "7days" ? "active" : ""} onClick={() => { setFilter("7days"); setPage(0); }}>
            <Clock3 size={14} /><span>Last 7 days</span>
          </button>
          <button className={filter === "30days" ? "active" : ""} onClick={() => { setFilter("30days"); setPage(0); }}>
            <Clock3 size={14} /><span>Last 30 days</span>
          </button>
          <div className="documents-filter-separator" />
          <h3>Tags</h3>
          <div className="documents-tag-list">
            {tags.length ? tags.map(([tag, count]) => (
              <button key={tag} className={filter === `tag:${tag}` ? "active" : ""} onClick={() => { setFilter(`tag:${tag}`); setPage(0); }}>
                <Tag size={13} /><span>{tag}</span><b>{count}</b>
              </button>
            )) : <p>No tags yet</p>}
          </div>
          <button className="documents-add-tag" onClick={() => toastInfo("Add tags from a document's details.")}><Plus size={13} /> Add a tag</button>
          <div className="documents-storage-meter">
            <div><strong>Storage</strong><span>{formatSize(overview.storage_bytes)}</span></div>
            <small>Files ready to search</small>
          </div>
        </aside>

        <section className="documents-library" aria-label="Documents" aria-busy={loading}>
          <div className="documents-library-heading">
            <div>
              <h2>{results ? "Search results" : "All documents"}</h2>
              <span>{results ? `${results.length} matching passages` : `${filteredDocuments.length} files`}</span>
            </div>
            {selected.size > 0 && (
              <div className="documents-selection-actions">
                <button onClick={() => onAskDocuments(Array.from(selected))}>Ask</button>
                {selected.size >= 2 && <button onClick={() => void onCompare()}>Compare</button>}
                {documents.some((doc) => selected.has(doc.id) && ["failed", "partial"].includes(doc.status)) && <button onClick={() => void onRetrySelected()}>Retry</button>}
                <button className="danger-action" onClick={onDeleteSelected}>Delete</button>
              </div>
            )}
          </div>

          {loading && !documents.length ? (
            <LibrarySkeleton />
          ) : loadError && !documents.length ? (
            <div className="documents-empty" role="alert">
              <FileText size={24} /><strong>Documents couldn't be loaded</strong><span>{loadError}</span>
              <button onClick={() => void fetchAll()}>Try again</button>
            </div>
          ) : results ? (
            <div className="documents-result-list">
              {results.map((result: any, index: number) => {
                const doc = documents.find((item) => item.id === result.document_id);
                const where = locationText(result);
                return (
                  <button className="documents-result" key={`${result.document_id}:${result.chunk_id || index}`} onClick={() => doc && openPreview(doc, result.page_number)}>
                    <span className="documents-result-title">{result.filename || doc?.name || "Document"}{where ? ` · ${where}` : ""}</span>
                    <span>{result.content || "No excerpt available."}</span>
                  </button>
                );
              })}
              {!results.length && <div className="documents-empty">No matching passages. Try a different search.</div>}
            </div>
          ) : (
            <>
              <label className="documents-select-all">
                <input type="checkbox" checked={selectedAll} onChange={() => {
                  setSelected((current) => {
                    const next = new Set(current);
                    if (selectedAll) filteredDocuments.forEach((doc) => next.delete(doc.id));
                    else filteredDocuments.forEach((doc) => next.add(doc.id));
                    return next;
                  });
                }} />
                <span>Select all documents</span>
              </label>
              <div className="documents-file-list">
                {pageDocuments.map((doc) => {
                  const Icon = fileIcon(extensionOf(doc));
                  return (
                    <article key={doc.id} className="documents-file-row">
                      <input type="checkbox" checked={selected.has(doc.id)} onChange={() => toggleSelected(doc.id)} aria-label={`Select ${doc.name}`} />
                      <button className="documents-file-open" onClick={() => openPreview(doc)} title={`Preview ${doc.name}`}>
                        <span className={`documents-file-icon file-${extensionOf(doc)}`}><Icon size={17} /></span>
                        <span className="documents-file-name">
                          <strong title={doc.name || "Untitled"}>{doc.name || "Untitled"}</strong>
                          <span className="documents-file-details">
                            <small>{documentKind(doc)} · {countLabel(doc.element_count, "section")} · {countLabel(doc.page_count, "page")} · {formatSize(doc.file_size)} · {formatDate(doc.created_at)}</small>
                            <StatusBadge status={doc.status} />
                          </span>
                        </span>
                      </button>
                      <button className="documents-file-preview" onClick={() => openPreview(doc)} aria-label={`Preview ${doc.name || "document"}`}>
                        <Eye size={15} /><span>Preview</span>
                      </button>
                      <div className="documents-row-menu">
                        <button className="documents-more" aria-label={`More actions for ${doc.name}`} onClick={() => setMenuDocId(menuDocId === doc.id ? null : doc.id)}><MoreHorizontal size={16} /></button>
                        {menuDocId === doc.id && (
                          <div className="documents-menu">
                            <button onClick={() => { setMenuDocId(null); openPreview(doc); }}>Preview</button>
                            <button onClick={() => onAskDocuments([doc.id])}>Ask questions</button>
                            <button onClick={() => void onDataset(doc)}>Create dataset</button>
                            <button onClick={() => void onExport(doc)}>Export</button>
                            {(doc.status === "failed" || doc.status === "partial") && <button onClick={() => void onRetry(doc)}>{retrying === doc.id ? "Retrying…" : "Retry"}</button>}
                            <button className="danger-action" disabled={deleting === doc.id} onClick={() => onDelete(doc)}><Trash2 size={13} /> Delete</button>
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
                {!filteredDocuments.length && (
                  <div className="documents-empty">
                    <FileText size={24} /><strong>{documents.length ? "No documents in this view" : "No documents yet"}</strong>
                    <span>{documents.length ? "Try a different filter or search." : "Upload or drop PDF, CSV, XLSX spreadsheet, or DOCX Word documents to get started."}</span>
                  </div>
                )}
              </div>
              {filteredDocuments.length > 0 && (
                <div className="documents-pagination">
                  <span>{page * pageSize + 1}–{Math.min((page + 1) * pageSize, filteredDocuments.length)} of {filteredDocuments.length}</span>
                  <button aria-label="Previous page" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}><ChevronLeft size={15} /></button>
                  <span>{page + 1} / {pageCount}</span>
                  <button aria-label="Next page" disabled={page + 1 >= pageCount} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}><ChevronRight size={15} /></button>
                </div>
              )}
            </>
          )}
        </section>

        <aside className="documents-assistant" aria-label="Document assistant">
          <div className="documents-assistant-heading">
            <span className="documents-assistant-icon"><Sparkles size={15} /></span>
            <div><h2>Document Assistant</h2><small>Grounded in your uploaded files</small></div>
            <span className="documents-assistant-live" title="Assistant ready" />
          </div>
          <ChatSessions
            chats={chats}
            activeId={conversationId}
            loading={chatsLoading}
            error={chatsError}
            onOpen={(id) => void onOpenChat(id)}
            onNew={onNewChat}
            onDelete={onDeleteChat}
            onReload={() => void loadChats()}
          />
          <div className="documents-assistant-messages" aria-live="polite" aria-busy={openingChat || chatLoading}>
            {openingChat && (
              <div className="doc-skeleton-list" aria-label="Opening chat">
                <span className="doc-skeleton" /><span className="doc-skeleton" /><span className="doc-skeleton" />
              </div>
            )}
            {!openingChat && !chatMessages.length && (
              <div className="documents-assistant-welcome">
                <span><Sparkles size={17} /></span>
                <strong>Ask questions about your documents</strong>
                <p>I’ll find relevant passages across your files and cite the page or rows for every answer.</p>
              </div>
            )}
            {!openingChat && chatMessages.map((message, index) => (
              <div className="documents-chat-turn" key={`${message.question}-${index}`}>
                {message.question && <div className="documents-chat-question">{message.question}</div>}
                <div className="documents-chat-answer">
                  <span className="documents-chat-sparkle"><Sparkles size={13} /></span>
                  {message.answerMode === "evidence" && <small className="documents-answer-mode">Grounded response · AI unavailable</small>}
                  {message.answerMode === "deterministic" && <small className="documents-answer-mode">Calculated from the tables in your documents</small>}
                  {message.error ? <p role="alert">{message.answer}</p> : <DocumentAnswer text={message.answer} />}
                  {message.visualization && (
                    <DocumentAnswerChart
                      visualization={message.visualization}
                      onViewSource={(sourceId) => openCitedSource(message, sourceId)}
                    />
                  )}
                  {message.error && <button className="documents-chat-retry" onClick={() => void onChat(message.question)}>Try again</button>}
                  {message.passages?.length > 0 && <div className="documents-chat-citations">
                    {(message.citations?.length ? message.citations : message.passages).slice(0, 4).map((citation: any, citationIndex: number) => {
                      const source = documents.find((doc) => doc.id === citation.document_id);
                      const where = locationText(citation);
                      return <button key={`${citation.document_id}:${citationIndex}`} onClick={() => source && openPreview(source, citation.page_number)}>
                        [{citation.index || citationIndex + 1}] {citation.filename || source?.name || "Document"}{where ? <span className="doc-citation-location"> · {where}</span> : null}
                      </button>;
                    })}
                  </div>}
                </div>
              </div>
            ))}
            {chatLoading && <div className="documents-assistant-thinking"><Sparkles size={13} /> Looking through your documents…</div>}
          </div>
          <div className="documents-assistant-suggestions">
            <span>Try asking</span>
            {prompts.map((prompt) => <button key={prompt} onClick={() => void onChat(prompt)}>{prompt}</button>)}
          </div>
          {selected.size > 0 && <div className="documents-chat-scope"><Check size={12} /> Answers scoped to {selected.size} selected document{selected.size === 1 ? "" : "s"}</div>}
          <form className="documents-chat-input" onSubmit={(event) => { event.preventDefault(); void onChat(); }}>
            <input ref={chatInputRef} value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="Ask a question about your documents…" aria-label="Ask the document assistant" />
            <button disabled={chatLoading || !chatInput.trim()} aria-label="Send question"><Send size={15} /></button>
          </form>
          <p className="documents-assistant-footnote"><Check size={12} /> Answers are based on your uploaded documents.</p>
        </aside>
      </section>

      {activeDocument && (
        <div className="documents-modal-backdrop" onClick={() => setActiveDocId(null)}>
          <section
            className="documents-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="documents-preview-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="documents-panel-heading">
              <div><span className="documents-panel-kicker">Document preview</span><h2 id="documents-preview-title" title={activeDocument.name}>{activeDocument.name || "Untitled document"}</h2></div>
              <button aria-label="Close preview" onClick={() => setActiveDocId(null)}><X size={18} /></button>
            </div>
            <div className="documents-preview-scroll">
              <div className="documents-paper">
                <div className="documents-paper-top"><span>ARIA DOCUMENT INSIGHTS</span><StatusBadge status={activeDocument.status} /></div>
                <h3>{activeDocument.name || "Untitled document"}</h3>
                <div className="documents-paper-meta">{countLabel(activeDocument.page_count, "page")} <span /> {formatSize(activeDocument.file_size)} <span /> {formatDate(activeDocument.created_at)}</div>
                {activeDocument.needs_reextract && (
                  <div className="doc-reextract-hint">
                    <span>This PDF was read by an older version of ARIA. Reading its tables again gives better table answers and page citations.</span>
                    <button
                      type="button"
                      className="doc-link-button"
                      disabled={retrying === activeDocument.id}
                      onClick={() => void onRetry(activeDocument, true)}
                    >
                      <RefreshCw size={12} /> {retrying === activeDocument.id ? "Reading tables…" : "Read tables again"}
                    </button>
                  </div>
                )}
                <section className="documents-summary" aria-label="Document summary">
                  <h4>Summary</h4>
                  {activeDocument.summary
                    ? <p className="documents-paper-summary">{activeDocument.summary}</p>
                    : <p className="documents-preview-hint">Preparing a plain-English summary…</p>}
                </section>
                {previewMetrics.length > 0 ? (
                  <div className="documents-chart">
                    <div className="documents-chart-heading"><strong>Extracted metrics</strong><BarChart3 size={14} /></div>
                    {previewMetrics.slice(0, 5).map((metric: any, index: number) => {
                      const maxValue = Math.max(...previewMetrics.slice(0, 5).map((item: any) => Math.abs(Number(item.value) || 0)), 1);
                      const width = Math.max(4, Math.abs(Number(metric.value) || 0) / maxValue * 100);
                      return <div className="documents-chart-row" key={`${metric.label}-${index}`}>
                        <span title={metric.label}>{metric.label}</span><i><b style={{ width: `${width}%` }} /></i><strong>{Number(metric.value).toLocaleString()}</strong>
                      </div>;
                    })}
                  </div>
                ) : (
                  <div className="documents-no-chart"><BarChart3 size={16} />No numeric metrics were extracted from this document.</div>
                )}
                <div className="documents-paper-stats">
                  <span><small>Sections</small><strong>{Number(activeDocument.element_count || 0).toLocaleString()}</strong></span>
                  <span><small>Search passages</small><strong>{Number(activeDocument.chunk_count || 0).toLocaleString()}</strong></span>
                  <span><small>Tables</small><strong>{Number(activeDocument.table_count || 0).toLocaleString()}</strong></span>
                </div>
              </div>
              <div className="documents-extracted">
                <div className="documents-extracted-heading"><strong>Extracted text</strong><span>{countLabel(previewChunks.length, "passage")}</span></div>
                {previewLoading && <div className="doc-skeleton-list" aria-label="Loading document details"><span className="doc-skeleton" /><span className="doc-skeleton" /><span className="doc-skeleton" /></div>}
                {previewError && <p className="documents-preview-error" role="alert">{previewError}</p>}
                {!previewLoading && previewChunks.slice(0, 5).map((chunk: any, index: number) => {
                  const cited = previewPage != null && Number(chunk?.metadata?.page) === previewPage;
                  return <article className={cited ? "is-cited" : ""} key={`${chunk?.metadata?.page || "chunk"}:${index}`}>
                    <small>{chunk?.metadata?.page ? `Page ${chunk.metadata.page}` : `Section ${index + 1}`}{cited ? " · citation" : ""}</small>
                    <DocumentAnswer text={chunk?.text || ""} />
                  </article>;
                })}
                {!previewLoading && !previewChunks.length && !previewError && <p className="documents-preview-hint">No extracted text is available.</p>}
              </div>
            </div>
          </section>
        </div>
      )}

      {compareDocs && (
        <div className="documents-modal-backdrop" onClick={() => setCompareDocs(null)}>
          <div className="documents-compare-modal" role="dialog" aria-modal="true" aria-label="Compare documents" onClick={(event) => event.stopPropagation()}>
            <header><h2>Compare documents</h2><button aria-label="Close comparison" onClick={() => setCompareDocs(null)}><X size={17} /></button></header>
            <div className="documents-compare-columns">
              {compareDocs.map((doc, index) => <article key={doc.id}>
                <h3>{doc.name || "Untitled"}</h3><small>{countLabel(doc.page_count, "page")} · {countLabel(compareChunks[index]?.length, "passage")}</small>
                {compareLoading
                  ? <div className="doc-skeleton-list" aria-label="Loading comparison"><span className="doc-skeleton" /><span className="doc-skeleton" /></div>
                  : (compareChunks[index] || []).slice(0, 8).map((chunk: any, chunkIndex: number) => <DocumentAnswer key={chunkIndex} text={chunk?.text || ""} />)}
              </article>)}
            </div>
          </div>
        </div>
      )}

      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          message={pendingConfirm.message}
          confirmLabel={pendingConfirm.confirmLabel}
          busy={confirmBusy}
          onConfirm={() => void runConfirm()}
          onCancel={() => { if (!confirmBusy) setPendingConfirm(null); }}
        />
      )}
    </div>
  );
}
