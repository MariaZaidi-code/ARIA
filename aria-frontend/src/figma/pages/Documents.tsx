import { useEffect, useState } from "react";
import { listDocuments, deleteDocument, retryDocument, searchDocuments, getDocument } from "../../services/api";
import { useToast } from "../../components/Toast";

function StatusPill({ status }: { status?: string }) {
  const s = status || "unknown";
  const palette: Record<string, string> = {
    ready: "from-emerald-500/20 to-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
    partial: "from-amber-500/20 to-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30",
    failed: "from-rose-500/20 to-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30",
    uploading: "from-sky-500/20 to-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/30",
  };
  const grad = palette[s] || "from-slate-500/20 to-slate-500/10 text-secondary-foreground dark:text-slate-300 border-slate-500/30";
  return (
    <span className={`px-2.5 py-1 rounded-full text-[10px] font-semibold uppercase tracking-wider border bg-gradient-to-r ${grad}`}>
      {s}
    </span>
  );
}

function formatDate(d: string | undefined) {
  if (!d) return "—";
  try { return new Date(d).toLocaleString(); } catch { return d; }
}

function formatSize(bytes?: number) {
  if (!bytes) return "—";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

export default function Documents() {
  const [documents, setDocuments] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [compareDocs, setCompareDocs] = useState<[any, any] | null>(null);
  const [compareChunks, setCompareChunks] = useState<[any[], any[]]>([[], []]);
  const [compareLoading, setCompareLoading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<any | null>(null);
  const [previewChunks, setPreviewChunks] = useState<any[]>([]);
  const [recentQueries, setRecentQueries] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('aria_doc_recent_queries') || '[]'); } catch { return []; }
  });
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<{ q: string; passages: any[] }[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const { error: toastError, success: toastSuccess, info: toastInfo } = useToast() as any;

  const fetchAll = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const r: any = await listDocuments();
      if (r.success) setDocuments(r.data || []);
    } catch (e: any) {
      setLoadError(e?.message || "Failed to load documents");
      toastError("Failed to load documents");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === documents.length) setSelected(new Set());
    else setSelected(new Set(documents.map((d) => d.id)));
  };

  const onDelete = async (id: string) => {
    if (!window.confirm("Delete this document? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await deleteDocument(id);
      setDocuments((d) => d.filter((x) => x.id !== id));
      setSelected((s) => { const n = new Set(s); n.delete(id); return n; });
      toastSuccess("Document deleted");
    } catch {
      toastError("Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  const onDeleteSelected = async () => {
    if (selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} document(s)? This cannot be undone.`)) return;
    for (const id of selected) {
      try {
        await deleteDocument(id);
        setDocuments((d) => d.filter((x) => x.id !== id));
      } catch {
        toastError(`Failed to delete ${id}`);
      }
    }
    setSelected(new Set());
    toastSuccess("Selected documents deleted");
    await fetchAll();
  };

  const onRetry = async (doc: any) => {
    setRetrying(doc.id);
    try {
      await retryDocument(doc.id);
      toastSuccess("Retry started");
      await fetchAll();
    } catch {
      toastError("Retry failed");
    } finally {
      setRetrying(null);
    }
  };

  const onRetrySelected = async () => {
    if (selected.size === 0) return;
    for (const id of selected) {
      try { await retryDocument(id); } catch { toastError(`Retry failed for ${id}`); }
    }
    toastSuccess("Retry started for selected");
    await fetchAll();
  };

  const onSearch = async () => {
    if (!query.trim()) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      const r: any = await searchDocuments(query, undefined, 20);
      if (r.success) setResults((r.data || []) as any);
    } catch {
      toastError("Search failed");
    } finally {
      setSearching(false);
    }
    if (query.trim()) {
      setRecentQueries((prev) => {
        const next = [query.trim(), ...prev.filter((q) => q !== query.trim())].slice(0, 8);
        try { localStorage.setItem('aria_doc_recent_queries', JSON.stringify(next)); } catch {}
        return next;
      });
    }
  };

  const clearSearch = () => {
    setQuery("");
    setResults(null);
  };

  const handleChat = async () => {
    if (!chatInput.trim()) return;
    const q = chatInput.trim();
    setChatInput('');
    setChatLoading(true);
    try {
      const ids = selected.size > 0 ? Array.from(selected) : undefined;
      const r: any = await searchDocuments(q, ids as any, 6);
      const passages = (r && r.success ? (r.data || []) : []);
      setChatMessages((prev) => [{ q, passages }, ...prev].slice(0, 10));
      if (passages.length === 0) toastInfo('No matching passages found. Try different keywords.');
    } catch {
      toastError('Search failed');
    } finally {
      setChatLoading(false);
    }
  };

  const onAsk = (docIds: string[]) => {
    const ids = docIds.join(",");
    window.location.hash = `#/copilot?docs=${encodeURIComponent(ids)}`;
    toastInfo("Opening Copilot with selected documents…");
  };

  const openPreview = async (doc: any) => {
    setPreviewDoc(doc);
    setPreviewChunks([]);
    setPreviewLoading(true);
    try {
      const r: any = await getDocument(doc.id);
      if (r?.success && r.data) setPreviewDoc({ ...doc, ...r.data });
      const c: any = await (await fetch(`/api/documents/${doc.id}/chunks`, { credentials: "include" })).json();
      if (c?.ok) {
        setPreviewChunks(c.chunks || []);
        if (c.summary) setPreviewDoc((prev: any) => prev ? { ...prev, summary: c.summary } : prev);
      }
    } catch {
      toastError("Could not load preview");
    } finally {
      setPreviewLoading(false);
    }
  };

  const openCompare = async () => {
    if (selected.size !== 2) { toastError('Select exactly 2 documents to compare'); return; }
    const ids = Array.from(selected);
    const d1 = documents.find((d) => d.id === ids[0]);
    const d2 = documents.find((d) => d.id === ids[1]);
    if (!d1 || !d2) return;
    setCompareDocs([d1, d2]);
    setCompareChunks([[], []]);
    setCompareLoading(true);
    try {
      const [c1, c2] = await Promise.all([
        (await fetch('/api/documents/' + ids[0] + '/chunks', { credentials: 'include' })).json(),
        (await fetch('/api/documents/' + ids[1] + '/chunks', { credentials: 'include' })).json(),
      ]);
      setCompareChunks([c1?.chunks || [], c2?.chunks || []]);
    } catch {
      toastError('Could not load comparison');
    } finally {
      setCompareLoading(false);
    }
  };

  const list = documents;
  const showSearchResults = results !== null;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 border border-primary/20 mb-3">
            <span className="w-1.5 h-1.5 rounded-full bg-primary" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-primary">Knowledge Base</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage, search, and ask questions about your uploaded PDF documents</p>
        </div>
        <div className="text-xs text-muted-foreground premium-card px-4 py-2 rounded-xl">
          {documents.length} {documents.length === 1 ? "document" : "documents"}
        </div>
      </div>


      {documents.length > 0 && (
        <div className="flex items-center gap-3 flex-wrap">
          <label className="inline-flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <input type="checkbox" checked={selected.size === documents.length && documents.length > 0} onChange={selectAll} className="rounded" />
            Select all
          </label>
          {selected.size > 0 && (
            <>
              <span className="text-xs text-muted-foreground">{selected.size} selected</span>
              <button onClick={() => onAsk(Array.from(selected))} className="px-3 py-1.5 rounded-lg text-xs font-medium premium-btn">
                Ask Questions
              </button>
              {selected.size === 2 && (
                <button onClick={openCompare} className="px-3 py-1.5 rounded-lg text-xs font-medium border border-white/30 dark:border-slate-700/30 hover:bg-card/40 dark:hover:bg-slate-800/40">
                  Compare
                </button>
              )}
              <button onClick={onRetrySelected} className="px-3 py-1.5 rounded-lg text-xs font-medium border border-white/30 dark:border-slate-700/30 hover:bg-card/40 dark:hover:bg-slate-800/40">
                Retry Selected
              </button>
              <button onClick={onDeleteSelected} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20 hover:bg-rose-500/20">
                Delete Selected
              </button>
            </>
          )}
        </div>
      )}

      {recentQueries.length > 0 && !showSearchResults && (
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-[11px] text-muted-foreground">Recent:</span>
          {recentQueries.map((q, i) => (
            <button key={i} onClick={() => { setQuery(q); }} className="px-2.5 py-1 rounded-full text-[11px] border border-border bg-secondary/40 text-secondary-foreground hover:bg-secondary hover:text-foreground">{q}</button>
          ))}
        </div>
      )}

      {documents.length > 0 && (
        <div className="premium-card rounded-2xl p-4 space-y-3">
          <span className="text-[11px] font-bold uppercase tracking-widest text-primary">Ask your documents</span>
          <div className="flex gap-2 items-center">
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleChat()}
              placeholder={selected.size > 0 ? 'Ask about ' + selected.size + ' selected document(s)...' : 'Ask across all documents...'}
              className="flex-1 px-4 py-2.5 rounded-xl bg-card/40 dark:bg-slate-900/40 border border-white/20 dark:border-slate-700/30 focus:outline-none focus:ring-2 focus:ring-primary/30 text-sm"
            />
            <button
              onClick={handleChat}
              disabled={chatLoading || !chatInput.trim()}
              className="premium-btn px-5 py-2.5 rounded-xl font-medium text-sm disabled:opacity-50"
            >
              {chatLoading ? 'Searching...' : 'Ask'}
            </button>
          </div>
          {chatMessages.length > 0 && (
            <div className="space-y-3 mt-2">
              {chatMessages.map((m, i) => (
                <div key={i} className="rounded-xl border border-border/60 bg-secondary/20 p-3 space-y-2">
                  <p className="text-sm font-semibold text-foreground">{m.q}</p>
                  {m.passages.length === 0 ? (
                    <p className="text-[12px] text-muted-foreground">No matching passages found.</p>
                  ) : (
                    <div className="space-y-2">
                      {m.passages.slice(0, 4).map((p: any, j: number) => (
                        <div key={j} className="rounded-lg bg-card/40 dark:bg-slate-900/30 p-2.5">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <span className="text-[10px] font-semibold text-primary truncate">{p.filename || 'Document'}</span>
                            {p.page_number && <span className="text-[10px] text-muted-foreground">Page {p.page_number}</span>}
                          </div>
                          <p className="text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-4">{p.content || ''}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {loading && documents.length === 0 && !loadError && (
        <div className="premium-card rounded-2xl p-12 text-center text-sm text-muted-foreground">Loading documents…</div>
      )}

      {!loading && loadError && documents.length === 0 && (
        <div className="premium-card rounded-2xl p-12 text-center">
          <h3 className="text-lg font-semibold mb-1">Documents couldn't be loaded</h3>
          <p className="text-sm text-muted-foreground">{loadError}</p>
          <button onClick={fetchAll} className="premium-btn px-5 py-2.5 rounded-xl font-medium text-sm mt-4">
            Retry
          </button>
        </div>
      )}

      {!loading && !loadError && ((showSearchResults && results.length === 0) || (!showSearchResults && documents.length === 0)) && (
        <div className="premium-card rounded-2xl p-12 text-center">
          <div className="text-5xl mb-4">{showSearchResults ? "🔍" : "📄"}</div>
          <h3 className="text-lg font-semibold mb-1">
            {showSearchResults ? `No results for "${query}"` : "No documents yet"}
          </h3>
          <p className="text-sm text-muted-foreground">
            {showSearchResults ? "Try a different search term." : "Upload PDF documents from the Data Sources page to get started."}
          </p>
        </div>
      )}

      {showSearchResults && results.length > 0 && (
        <div className="space-y-3">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
            {results.length} matching {results.length === 1 ? "passage" : "passages"}
          </p>
          {results.map((result: any, i: number) => {
            const sourceName = result.filename || documents.find((doc) => doc.id === result.document_id)?.name || "PDF document";
            return (
              <article key={`${result.document_id || "doc"}:${result.chunk_id || i}:${i}`} className="premium-card rounded-2xl p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-semibold text-sm text-foreground truncate">{sourceName}</h3>
                  <span className="text-[11px] text-muted-foreground whitespace-nowrap">
                    {result.page_number ? `Page ${result.page_number}` : "PDF excerpt"}
                  </span>
                </div>
                {result.section && <p className="text-[11px] text-muted-foreground">{result.section}</p>}
                <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">{result.content || "No excerpt available."}</p>
                {result.document_id && (
                  <button
                    onClick={() => { window.location.hash = `#/copilot?docs=${encodeURIComponent(result.document_id)}`; }}
                    className="text-[11px] font-semibold text-blue-700 dark:text-blue-400 hover:underline"
                  >
                    Ask about this →
                  </button>
                )}
              </article>
            );
          })}
        </div>
      )}

      {!showSearchResults && list.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {list.map((doc) => (
            <article key={doc.id} className="premium-card rounded-2xl p-5 space-y-4 hover:shadow-lg transition-shadow">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <input type="checkbox" checked={selected.has(doc.id)} onChange={() => toggleSelect(doc.id)} className="rounded" />
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-base truncate">{doc.name || doc.original_name || "Untitled"}</h3>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap text-[11px] text-muted-foreground">
                      <span>{formatSize(doc.file_size)}</span>
                      <span>·</span>
                      <span>{doc.page_count || 0} pages</span>
                      <span>·</span>
                      <span>{formatDate(doc.created_at)}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {doc.document_type && doc.document_type !== 'pdf' && (
                    <span className="px-2 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider border border-border bg-secondary text-muted-foreground">{doc.document_type}</span>
                  )}
                  <StatusPill status={doc.status} />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-card/30 dark:bg-slate-800/30 p-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Elements</div>
                  <div className="text-sm font-semibold mt-0.5">{doc.element_count || 0}</div>
                </div>
                <div className="rounded-lg bg-card/30 dark:bg-slate-800/30 p-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Chunks</div>
                  <div className="text-sm font-semibold mt-0.5">{doc.chunk_count || 0}</div>
                </div>
                <div className="rounded-lg bg-card/30 dark:bg-slate-800/30 p-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Tables</div>
                  <div className="text-sm font-semibold mt-0.5">{doc.table_count || 0}</div>
                </div>
              </div>

              {doc.summary && (
                <p className="text-[12px] text-secondary-foreground leading-relaxed line-clamp-3">{doc.summary}</p>
              )}

              {doc.error_message && (
                <div className="text-[11px] rounded-lg bg-rose-500/10 border border-rose-500/20 px-3 py-2 text-rose-600 dark:text-rose-400">
                  {doc.error_message}
                </div>
              )}

              <div className="flex gap-2 pt-1">
                {(doc.status === "ready" || doc.status === "partial") && (
                  <button
                    className="flex-1 px-3 py-2 rounded-lg text-xs font-medium premium-btn"
                    onClick={() => onAsk([doc.id])}
                  >
                    Ask Questions
                  </button>
                )}
                <button
                  onClick={() => openPreview(doc)}
                  className="px-3 py-2 rounded-lg text-xs font-medium border border-white/30 dark:border-slate-700/30 hover:bg-card/40 dark:hover:bg-slate-800/40"
                >
                  Preview
                </button>
                {(doc.status === "failed" || doc.status === "partial") && (
                  <button
                    onClick={() => onRetry(doc)}
                    disabled={retrying === doc.id}
                    className="flex-1 px-3 py-2 rounded-lg text-xs font-medium border border-white/30 dark:border-slate-700/30 hover:bg-card/40 dark:hover:bg-slate-800/40 disabled:opacity-50"
                  >
                    {retrying === doc.id ? "Retrying…" : "Retry"}
                  </button>
                )}
                <button
                  onClick={() => onDelete(doc.id)}
                  disabled={deleting === doc.id}
                  className="px-3 py-2 rounded-lg text-xs font-medium bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20 hover:bg-rose-500/20 disabled:opacity-50"
                >
                  {deleting === doc.id ? "…" : "Delete"}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {compareDocs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={() => setCompareDocs(null)}>
          <div className="bg-card border border-border rounded-2xl shadow-2xl max-w-6xl w-full max-h-[85vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h3 className="font-semibold text-foreground">Document comparison</h3>
              <button onClick={() => setCompareDocs(null)} className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground">X</button>
            </div>
            <div className="grid grid-cols-2 gap-0 flex-1 overflow-hidden">
              {[0, 1].map((idx) => (
                <div key={idx} className={`p-4 overflow-y-auto ${idx === 0 ? 'border-r border-border' : ''}`}>
                  <h4 className="font-semibold text-sm text-foreground mb-2 truncate">{compareDocs[idx]?.name || compareDocs[idx]?.original_name}</h4>
                  <div className="text-[11px] text-muted-foreground mb-3">{compareDocs[idx]?.page_count || 0} pages - {compareChunks[idx].length} chunks</div>
                  {compareLoading && <p className="text-sm text-muted-foreground">Loading...</p>}
                  {!compareLoading && (
                    <div className="space-y-2">
                      {compareChunks[idx].slice(0, 12).map((c, i) => (
                        <div key={i} className="rounded-lg bg-secondary/30 p-2.5">
                          <p className="text-[10px] text-muted-foreground mb-1">{c?.metadata?.page ? 'Page ' + c.metadata.page : 'Chunk ' + (i + 1)}</p>
                          <p className="text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-5">{c?.text || ''}</p>
                        </div>
                      ))}
                      {compareChunks[idx].length === 0 && <p className="text-sm text-muted-foreground">No extracted text.</p>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {previewDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={() => setPreviewDoc(null)}>
          <div className="bg-card border border-border rounded-2xl shadow-2xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h3 className="font-semibold text-foreground truncate">{previewDoc.name || previewDoc.original_name || "Document"}</h3>
              <button onClick={() => setPreviewDoc(null)} className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground">✕</button>
            </div>
            <div className="p-4 overflow-y-auto flex-1 space-y-3">
              {previewLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
              {!previewLoading && (
                <>
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    <div className="rounded-lg bg-secondary/40 p-2">
                      <div className="text-[10px] uppercase text-muted-foreground">Pages</div>
                      <div className="font-semibold mt-0.5">{previewDoc.page_count || 0}</div>
                    </div>
                    <div className="rounded-lg bg-secondary/40 p-2">
                      <div className="text-[10px] uppercase text-muted-foreground">Chunks</div>
                      <div className="font-semibold mt-0.5">{previewDoc.chunk_count || 0}</div>
                    </div>
                    <div className="rounded-lg bg-secondary/40 p-2">
                      <div className="text-[10px] uppercase text-muted-foreground">Tables</div>
                      <div className="font-semibold mt-0.5">{previewDoc.table_count || 0}</div>
                    </div>
                  </div>
                  {previewDoc.summary && (
                    <div>
                      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Summary</p>
                      <p className="text-sm text-foreground/90 leading-relaxed">{previewDoc.summary}</p>
                    </div>
                  )}
                  {previewChunks.length > 0 && (
                    <div>
                      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Extracted text ({previewChunks.length} chunks)</p>
                      <div className="space-y-2 max-h-60 overflow-y-auto">
                        {previewChunks.slice(0, 6).map((c: any, i: number) => (
                          <div key={i} className="rounded-lg bg-secondary/30 p-2.5">
                            <p className="text-[10px] text-muted-foreground mb-1">{c?.metadata?.page ? `Page ${c.metadata.page}` : `Chunk ${i + 1}`}</p>
                            <p className="text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap line-clamp-6">{c?.text || ""}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div>
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Search within this document</p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        placeholder="Search passages…"
                        className="flex-1 px-3 py-2 rounded-lg bg-card/40 border border-white/20 dark:border-slate-700/30 text-sm"
                        onKeyDown={async (e) => {
                          if (e.key === "Enter") {
                            const q = (e.target as HTMLInputElement).value.trim();
                            if (!q) return;
                            try {
                              const r: any = await searchDocuments(q, [previewDoc.id] as any, 8);
                              if (r.success) {
                                const el = document.getElementById("preview-results");
                                if (el) el.innerHTML = (r.data || []).map((x: any) => `<div class="mb-3 pb-3 border-b border-border last:border-0"><p class="text-xs text-muted-foreground mb-1">${x.page_number ? "Page " + x.page_number : "Excerpt"}</p><p class="text-sm">${x.content || ""}</p></div>`).join("");
                              }
                            } catch { toastError("Search failed"); }
                          }
                        }}
                      />
                    </div>
                    <div id="preview-results" className="mt-3 max-h-60 overflow-y-auto" />
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
