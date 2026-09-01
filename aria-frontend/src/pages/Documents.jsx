import { useEffect, useState } from "react";
import { listDocuments, deleteDocument, retryDocument, searchDocuments } from "../services/api";

function Documents({
  currentUser,
  onNavigate,
}) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [retrying, setRetrying] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [showSearch, setShowSearch] = useState(false);

  const formatDate = (dateValue) => {
    if (!dateValue) return "Unknown date";
    return new Date(dateValue).toLocaleString();
  };

  const formatFileSize = (bytes) => {
    if (!bytes) return "Unknown";
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
  };

  const getStatusLabel = (status) => {
    const labels = {
      uploading: "Uploading",
      uploaded: "Uploaded",
      validating: "Validating",
      detecting: "Detecting Type",
      extracting: "Extracting",
      ocr: "OCR Processing",
      handwriting: "Handwriting Recognition",
      understanding: "Understanding",
      chunking: "Chunking",
      embedding: "Generating Embeddings",
      indexing: "Indexing",
      ready: "Ready",
      failed: "Failed",
      partial: "Partial",
      deleting: "Deleting",
      deleted: "Deleted",
    };
    return labels[status] || status;
  };

  const getStatusClass = (status) => {
    if (status === "ready") return "status-ready";
    if (status === "failed") return "status-failed";
    if (status === "partial") return "status-partial";
    if (status === "uploading" || status === "validating" || status === "detecting" || 
        status === "extracting" || status === "ocr" || status === "handwriting" || 
        status === "understanding" || status === "chunking" || status === "embedding" || 
        status === "indexing") return "status-processing";
    return "";
  };

  const fetchDocuments = async () => {
    setLoading(true);
    try {
      const response = await listDocuments();
      if (response.success) {
        setDocuments(response.data);
      }
    } catch (error) {
      console.error("Failed to fetch documents:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [currentUser?.email]);

  const handleDelete = async (documentId) => {
    if (!window.confirm("Are you sure you want to delete this document? This action cannot be undone.")) {
      return;
    }

    setDeleting(documentId);
    try {
      await deleteDocument(documentId);
      setDocuments(documents.filter(d => d.id !== documentId));
    } catch (error) {
      console.error("Delete failed:", error);
      alert("Failed to delete document");
    } finally {
      setDeleting(null);
    }
  };

  const handleRetry = async (document) => {
    setRetrying(document.id);
    try {
      await retryDocument(document.id);
      await fetchDocuments();
    } catch (error) {
      console.error("Retry failed:", error);
      alert("Failed to retry document processing");
    } finally {
      setRetrying(null);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }

    setLoading(true);
    try {
      const response = await searchDocuments(searchQuery, null, 20);
      if (response.success) {
        setSearchResults(response.data);
        setShowSearch(true);
      }
    } catch (error) {
      console.error("Search failed:", error);
    } finally {
      setLoading(false);
    }
  };

  const clearSearch = () => {
    setSearchQuery("");
    setSearchResults([]);
    setShowSearch(false);
  };

  const handleOpenDocument = (document) => {
    // Navigate to Ask ARIA with document context
    onNavigate("askAria");
    // Could also pass document ID to filter search
  };

  const displayDocuments = showSearch ? searchResults : documents;

  return (
    <div className="documents-page">
      {/* PAGE HEADER */}
      <div className="page-header">
        <div>
          <h1>Documents</h1>
          <p>Manage your uploaded PDF documents</p>
        </div>
        <div className="documents-count-badge">
          {documents.length} {documents.length === 1 ? "document" : "documents"}
        </div>
      </div>

      {/* SEARCH BAR */}
      <div className="documents-toolbar">
        <div className="search-wrapper">
          <input
            type="text"
            className="documents-search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search across all documents..."
          />
          <button 
            className="search-button"
            onClick={handleSearch}
            disabled={loading || !searchQuery.trim()}
          >
            Search
          </button>
          {showSearch && (
            <button className="clear-search-button" onClick={clearSearch}>
              Clear
            </button>
          )}
        </div>
      </div>

      {/* EMPTY STATE */}
      {documents.length === 0 && !showSearch && (
        <section className="documents-empty-state">
          <div className="empty-state-icon" aria-hidden="true">
            📄
          </div>
          <h3>No documents yet</h3>
          <p>Upload PDF documents from the Data Sources page to get started.</p>
          <div className="empty-state-actions">
            <button
              type="button"
              className="primary-button"
              onClick={() => onNavigate && onNavigate("dataSource")}
            >
              Upload Document →
            </button>
          </div>
        </section>
      )}

      {/* SEARCH RESULTS */}
      {showSearch && searchResults.length === 0 && searchQuery && (
        <section className="documents-empty-state">
          <div className="empty-state-icon" aria-hidden="true">
            🔍
          </div>
          <h3>No results for “{searchQuery}”</h3>
          <p>Try a different search term.</p>
        </section>
      )}

      {/* DOCUMENTS LIST */}
      {displayDocuments.length > 0 && (
        <div className="documents-list">
          {displayDocuments.map((doc) => (
            <article key={doc.id} className="document-card">
              <div className="document-card-header">
                <div className="document-info">
                  <h3>{doc.name || doc.original_name || "Untitled"}</h3>
                  <div className="document-meta">
                    <span>{formatFileSize(doc.file_size)}</span>
                    <span>{doc.page_count} pages</span>
                    <span className={`document-status ${getStatusClass(doc.status)}`}>
                      {getStatusLabel(doc.status)}
                    </span>
                  </div>
                </div>
                <div className="document-type-badge">
                  {doc.document_type || "PDF"}
                </div>
              </div>

              <div className="document-details">
                <div className="detail-row">
                  <span className="detail-label">Uploaded</span>
                  <span className="detail-value">{formatDate(doc.created_at)}</span>
                </div>
                {doc.completed_at && (
                  <div className="detail-row">
                    <span className="detail-label">Processed</span>
                    <span className="detail-value">{formatDate(doc.completed_at)}</span>
                  </div>
                )}
                <div className="detail-row">
                  <span className="detail-label">Elements</span>
                  <span className="detail-value">{doc.element_count || 0}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Chunks</span>
                  <span className="detail-value">{doc.chunk_count || 0}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Tables</span>
                  <span className="detail-value">{doc.table_count || 0}</span>
                </div>
                {doc.processing_method && (
                  <div className="detail-row">
                    <span className="detail-label">Method</span>
                    <span className="detail-value">{doc.processing_method}</span>
                  </div>
                )}
              </div>

              {doc.error_message && (
                <div className="document-error">
                  <strong>Error:</strong> {doc.error_message}
                </div>
              )}

              <div className="document-actions">
                <button
                  className="doc-action-button primary"
                  onClick={() => handleOpenDocument(doc)}
                  disabled={doc.status !== "ready" && doc.status !== "partial"}
                >
                  {doc.status === "ready" || doc.status === "partial" 
                    ? "Ask Questions" 
                    : "Not Ready"}
                </button>
                {doc.status === "failed" && (
                  <button
                    className="doc-action-button secondary"
                    onClick={() => handleRetry(doc)}
                    disabled={retrying === doc.id}
                  >
                    {retrying === doc.id ? "Retrying..." : "Retry"}
                  </button>
                )}
                {doc.status === "partial" && (
                  <button
                    className="doc-action-button secondary"
                    onClick={() => handleRetry(doc)}
                    disabled={retrying === doc.id}
                  >
                    {retrying === doc.id ? "Retry Failed Pages..." : "Retry Failed Pages"}
                  </button>
                )}
                <button
                  className="doc-action-button danger"
                  onClick={() => handleDelete(doc.id)}
                  disabled={deleting === doc.id}
                >
                  {deleting === doc.id ? "Deleting..." : "Delete"}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export default Documents;