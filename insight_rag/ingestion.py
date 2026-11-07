"""Text-PDF ingestion shared by every upload entry point; no OCR or LLM calls."""
from __future__ import annotations
import hashlib
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from .config import MAX_PDF_MB
from .diagnostics import stage, record, increment
from .enterprise_quality import quarantine_score
from .pdf_ingest import extract_pdf_documents
from .storage import RAGMetadataStore, UserPGVectorStore

def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

RAG_SCHEMA_VERSION = 3  # 3 = geometry-aware tables (no text/table duplication)


def _annotate_quarantine(documents) -> None:
    """Injection containment: flag high-risk chunks at ingestion so every
    downstream path can exclude them from LLM context."""
    quarantined = 0
    for doc in documents:
        try:
            verdict = quarantine_score(doc.page_content or "", scope="document")
        except Exception:
            verdict = {"quarantined": False, "score": 0, "regex_hits": []}
        if verdict.get("quarantined"):
            quarantined += 1
            doc.metadata["quarantined"] = True
            doc.metadata["quarantine_score"] = verdict.get("score", 0)
            doc.metadata["quarantine_labels"] = list(verdict.get("regex_hits") or [])
        else:
            doc.metadata.setdefault("quarantined", False)
    if quarantined:
        logging.getLogger(__name__).warning(
            "Ingestion quarantined %d/%d chunks (injection containment).",
            quarantined, len(documents),
        )
        record("ingestion_quarantined_chunks", quarantined)


class PDFIngestion:
    def __init__(self, user_id):
        self.user_id = str(user_id)
        self.metadata = RAGMetadataStore(user_id)

    def ingest_pdf(self, pdf_path: str | Path, *, original_filename: str, progress=None) -> dict:
        """Ingest one text PDF. ``progress(stage)`` is called at each stage boundary."""
        with self.metadata.mutation_lock():
            with stage("ingestion_total"):
                return self._ingest_pdf(pdf_path, original_filename=original_filename,
                                        progress=progress or (lambda _stage: None))

    def _ingest_pdf(self, pdf_path: str | Path, *, original_filename: str, progress) -> dict:
        progress("validating")
        path = Path(pdf_path)
        filename = PureWindowsPath(Path(original_filename).name).name
        if path.suffix.lower() != ".pdf" or not filename.lower().endswith(".pdf"):
            raise ValueError("Only PDF files are supported in the current Insight RAG version.")
        if not path.exists() or not path.is_file():
            raise ValueError("Uploaded PDF could not be found.")

        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            raise ValueError("Uploaded PDF is empty.")
        if size_bytes > MAX_PDF_MB * 1024 * 1024:
            raise ValueError(f"PDF is larger than the current {MAX_PDF_MB} MB limit.")
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError("The uploaded file does not appear to be a valid PDF.")

        digest = _sha256_file(path)
        existing = self.metadata.find_by_sha256(digest)
        if existing:
            record("ingestion_duplicate", True)
            return {"ok": True, "duplicate": True, "document": existing}

        document_id = str(uuid.uuid4())
        progress("extracting")
        with stage("pdf_extraction"):
            documents, stats = extract_pdf_documents(
                path,
                document_id=document_id,
                filename=filename,
            )
        _annotate_quarantine(documents)

        vector_store = UserPGVectorStore(self.user_id)
        chunk_ids = [str(doc.metadata["chunk_id"]) for doc in documents]
        try:
            progress("indexing")
            with stage("vector_index_write"):
                vector_store.add_documents(documents)

            progress("saving")
            destination = self.metadata.document_file_path(document_id)
            shutil.copyfile(path, destination)
            self.metadata.save_chunks(document_id, documents)

            quality = dict(stats.get("ingestion_quality") or {})
            document_record = {
                "document_id": document_id,
                "filename": filename,
                "sha256": digest,
                "size_bytes": size_bytes,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pages": stats["pages"],
                "tables": stats["tables"],
                "text_chunks": stats["text_chunks"],
                "table_chunks": stats["table_chunks"],
                "total_chunks": stats["total_chunks"],
                "text_chars": stats.get("text_chars", 0),
                "ingestion_quality": quality,
                "chunk_ids": chunk_ids,
                "rag_schema_version": RAG_SCHEMA_VERSION,
                "status": "ready",
                "processing_method": "text_pdf_pgvector",
            }
            self.metadata.put_document(document_record)
        except Exception as original_error:
            # Consistent rollback: PGVector index and filesystem must agree.
            # A failed index cleanup leaves a partial (unhealthy) state, so
            # fail loudly with both errors chained instead of reporting OK.
            try:
                vector_store.delete_chunks(chunk_ids)
            except Exception as cleanup_error:
                logging.getLogger(__name__).error(
                    "Ingestion rollback requires index cleanup: %s",
                    type(cleanup_error).__name__,
                )
                self.metadata.document_file_path(document_id).unlink(missing_ok=True)
                self.metadata.chunks_path(document_id).unlink(missing_ok=True)
                raise RuntimeError(
                    "PDF ingestion failed and index rollback did not complete; "
                    "no partial document is reported as healthy."
                ) from cleanup_error
            self.metadata.document_file_path(document_id).unlink(missing_ok=True)
            self.metadata.chunks_path(document_id).unlink(missing_ok=True)
            raise

        record("ingestion_quality_grade", (stats.get("ingestion_quality") or {}).get("grade", "unknown"))
        increment("ingested_chunks", len(documents))
        return {"ok": True, "duplicate": False, "document": document_record}


    def reindex(self, document_id):
        """Repair an owned index from stored text, without OCR or LLM calls."""
        with self.metadata.mutation_lock():
            record = self.metadata.get_document(document_id)
            if not record:
                raise ValueError("Document not found. Upload the text PDF first.")
            chunks = self.metadata.load_chunks(document_id)
            if not chunks:
                raise ValueError("No saved text chunks. Please upload the text PDF again.")
            for chunk in chunks:
                chunk.metadata["document_id"] = document_id
                chunk.metadata.setdefault("filename", record.get("filename", "document.pdf"))
                if not chunk.metadata.get("chunk_id"):
                    raise ValueError("Saved index metadata is incomplete. Upload the text PDF again.")
            try:
                UserPGVectorStore(self.user_id).add_documents(chunks)
            except Exception:
                record.update(status="failed", error_message="Index repair failed; check the RAG database and retry.")
                self.metadata.put_document(record)
                raise
            record.update(status="ready", error_message=None, chunk_ids=[c.metadata["chunk_id"] for c in chunks],
                          total_chunks=len(chunks), pages=record.get("pages", record.get("page_count", 0)))
            self.metadata.save_chunks(document_id, chunks)
            self.metadata.put_document(record)
            return {"ok": True, "document": record}

    def rechunk(self, document_id):
        """Rebuild a PDF's chunks from its stored file with the current extractor.

        Used to migrate documents ingested before geometry-aware tables. Chunk
        ids are deterministic, so unchanged chunks are upserted in place; ids
        that no longer exist are removed afterwards. If indexing fails, the
        previous chunks are written back so the document keeps working.
        """
        with self.metadata.mutation_lock():
            record = self.metadata.get_document(document_id)
            if not record:
                raise ValueError("Document not found. Upload the text PDF first.")
            if str(record.get("source_type") or "pdf") != "pdf":
                raise ValueError("Only PDF documents can be re-extracted; use repair for other formats.")
            pdf_path = self.metadata.document_file_path(document_id)
            if not pdf_path.exists():
                raise ValueError("The original PDF is no longer stored. Please upload it again.")
            old_chunks = self.metadata.load_chunks(document_id)
            documents, stats = extract_pdf_documents(
                pdf_path, document_id=document_id,
                filename=record.get("filename", "document.pdf"),
            )
            _annotate_quarantine(documents)
            new_ids = [str(doc.metadata["chunk_id"]) for doc in documents]
            stale_ids = [str(c.metadata.get("chunk_id")) for c in old_chunks
                         if c.metadata.get("chunk_id") and str(c.metadata.get("chunk_id")) not in set(new_ids)]
            vector_store = UserPGVectorStore(self.user_id)
            try:
                vector_store.add_documents(documents)
            except Exception:
                # Restore: drop ids only the new extraction introduced, then
                # re-upsert the previous chunks over any that were overwritten.
                old_ids = {str(c.metadata.get("chunk_id")) for c in old_chunks}
                try:
                    vector_store.delete_chunks([cid for cid in new_ids if cid not in old_ids])
                    if old_chunks:
                        vector_store.add_documents(old_chunks)
                except Exception:
                    record.update(status="failed",
                                  error_message="Re-extraction failed; use Retry to repair the index.")
                    self.metadata.put_document(record)
                raise
            if stale_ids:
                vector_store.delete_chunks(stale_ids)
            self.metadata.save_chunks(document_id, documents)
            record.update(
                status="ready", error_message=None, chunk_ids=new_ids,
                pages=stats["pages"], tables=stats["tables"],
                text_chunks=stats["text_chunks"], table_chunks=stats["table_chunks"],
                total_chunks=stats["total_chunks"], text_chars=stats.get("text_chars", 0),
                ingestion_quality=dict(stats.get("ingestion_quality") or {}),
                rag_schema_version=RAG_SCHEMA_VERSION,
            )
            self.metadata.put_document(record)
            return {"ok": True, "document": record, "rechunked": True}
