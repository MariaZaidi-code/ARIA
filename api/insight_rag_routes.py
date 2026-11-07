"""PDF-RAG endpoints for ARIA's existing Industry Insight Agent.

RAG is an Insight Agent capability, not a fifth autonomous agent.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
import zipfile
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import ConfigDict, BaseModel, Field

from core.deps import get_current_user, require_writable
from core.errors import sanitize_error
from insight_agent.industry import IndustryInsightAgent as InsightAgent
from insight_rag import InsightPDFRAG
from insight_rag.config import (
    MAX_PDF_MB,
    RAG_DATABASE_URL,
    RAG_LLM_MODEL,
    RAG_PIPELINE_VERSION,
    validate_rag_config,
)
from insight_rag.jobs import MAX_BATCH_FILES, UPLOAD_JOBS
from insight_rag.storage import (
    ConversationStore,
    RAGMetadataStore,
    UserPGVectorStore,
    metadata_backend_name,
    probe_vector_database,
)
from llm_provider import create_provider

router = APIRouter(prefix="/api/insight/pdf", tags=["Insight PDF RAG"])
_DOCUMENT_MAX_UNPACKED_BYTES = 250 * 1024 * 1024
_DOCUMENT_MAX_ARCHIVE_ENTRIES = 20_000
_SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".docx"}
_INGEST_UNAVAILABLE = (
    "I couldn't index that document right now. "
    "Please check the document and search service, then try again."
)


class PDFChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    question: str = Field(min_length=2, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=80)
    document_ids: list[str] | None = Field(default=None, max_length=20)
    document_only: bool = False


def _capability(user_id: str | int) -> InsightPDFRAG:
    """Attach PDF-RAG to the session's selected provider and models."""
    from core.config import get_session, resolve_provider_key
    from insight_rag.providers import configure_rag_models
    from llm_provider import PROVIDERS

    session = get_session(int(user_id))
    name = str(session.get("provider_name") or "local").strip().lower()
    if name not in PROVIDERS:
        raise ValueError("Selected AI provider is not supported.")
    models = dict((session.get("provider_models") or {}).get(name) or {})
    default_model = (models.get("semi") or models.get("story") or models.get("sql")
                     or RAG_LLM_MODEL)
    for role in ("rag", "rag_scope", "rag_rewrite", "rag_verify", "rag_plan"):
        models.setdefault(role, default_model)
    api_key = None if name == "local" else resolve_provider_key(
        name, (session.get("api_keys") or {}))
    provider = create_provider(name, api_key=api_key, models=models)
    try:
        configure_rag_models(provider)
    except ValueError:
        pass
    insight_agent = InsightAgent(provider=provider)
    return InsightPDFRAG(insight_agent=insight_agent, user_id=user_id)


def _validate_office_archive(path: Path, required_member: str) -> None:
    """Bound Office archive expansion before handing it to a document parser."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > _DOCUMENT_MAX_ARCHIVE_ENTRIES:
                raise ValueError("The Office document contains too many entries.")
            if sum(entry.file_size for entry in entries) > _DOCUMENT_MAX_UNPACKED_BYTES:
                raise ValueError("The Office document expands beyond the supported size.")
            if required_member not in archive.namelist():
                raise ValueError("The uploaded file is not a valid Office document.")
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid Office document.") from exc


@router.get("/health")
def pdf_rag_health(user: dict = Depends(get_current_user)):
    """Authenticated readiness/quality snapshot without exposing secrets or PDF text."""
    config_error = None
    try:
        validate_rag_config()
    except RuntimeError as exc:
        config_error = str(exc)

    documents = RAGMetadataStore(user["user_id"]).list_documents()
    quality_counts = Counter(
        str((document.get("ingestion_quality") or {}).get("grade") or "unknown")
        for document in documents
    )
    from core.config import get_session, resolve_provider_key
    session = get_session(user["user_id"])
    selected_provider = session.get("provider_name") or "local"
    provider_configured = (selected_provider == "local" or bool(
        resolve_provider_key(selected_provider, session.get("api_keys") or {})))
    provider_configured = provider_configured and not bool(session.get("_provider_error"))
    database_configured = bool(RAG_DATABASE_URL)
    probe = probe_vector_database() if database_configured else {
        "reachable": False, "pgvector": False, "error": "not_configured"}
    ready = (not config_error and provider_configured and database_configured
             and probe["reachable"] and probe["pgvector"])
    return {
        "ok": True,
        "ready": ready,
        "status": "ready" if ready else "degraded",
        "pipeline_version": RAG_PIPELINE_VERSION,
        "model": RAG_LLM_MODEL if selected_provider == "deepseek" else None,
        "provider_name": selected_provider,
        "provider_configured": provider_configured,
        "database_configured": database_configured,
        "database_reachable": probe["reachable"],
        "pgvector_available": probe["pgvector"],
        "database_error": probe["error"],
        "metadata_backend": metadata_backend_name(),
        "config_valid": config_error is None,
        "config_error": config_error,
        "documents": len(documents),
        "ingestion_quality": dict(quality_counts),
    }


def _spool_upload(file: UploadFile) -> tuple[Path, str, str, int]:
    """Validate the extension and stream one upload to a bounded temp file."""
    filename = Path(file.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Supported document formats are PDF, CSV, XLSX, and DOCX.",
        )
    temp_path = None
    max_bytes = MAX_PDF_MB * 1024 * 1024
    written = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp:
            temp_path = Path(temp.name)
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Document exceeds the current {MAX_PDF_MB} MB limit.",
                    )
                temp.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    except BaseException:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        try:
            file.file.close()
        except Exception:
            pass
    return temp_path, filename, extension, written


def _ingest_spooled(user_id, temp_path: Path, filename: str, extension: str, written: int,
                    progress=None) -> dict:
    """Ingest a spooled upload through the canonical pipeline for its format."""
    progress = progress or (lambda _stage: None)
    if extension == ".pdf":
        from insight_rag.ingestion import PDFIngestion
        return PDFIngestion(user_id).ingest_pdf(
            temp_path, original_filename=filename, progress=progress)

    progress("validating")
    capability = _capability(user_id)
    element_count = 0
    if extension == ".csv":
        progress("indexing")
        result = capability.ingest_tabular(temp_path, filename=filename, table_name=filename)
        element_count = int((result.get("document") or {}).get("row_count") or 0)
    elif extension == ".xlsx":
        _validate_office_archive(temp_path, "xl/workbook.xml")
        import pandas as pd

        progress("extracting")
        try:
            sheets = pd.read_excel(temp_path, sheet_name=None)
        except Exception as exc:
            raise ValueError("The uploaded workbook could not be read.") from exc
        frames = [(name, frame) for name, frame in sheets.items() if not frame.empty]
        if not frames:
            raise ValueError("The workbook contains no usable rows.")
        worksheet_column = "_worksheet"
        while any(worksheet_column in frame.columns for _, frame in frames):
            worksheet_column = f"_{worksheet_column}"
        for name, frame in frames:
            frame[worksheet_column] = name
        workbook = pd.concat([frame for _, frame in frames], ignore_index=True, sort=False)
        progress("indexing")
        result = capability.ingest_tabular(workbook, filename=filename, table_name=filename)
        element_count = int((result.get("document") or {}).get("row_count") or len(workbook))
    else:
        _validate_office_archive(temp_path, "word/document.xml")
        from docx import Document as WordDocument

        progress("extracting")
        try:
            word_document = WordDocument(temp_path)
        except Exception as exc:
            raise ValueError("The uploaded Word document could not be read.") from exc
        records = [
            {"Section": f"Paragraph {index + 1}", "Text": paragraph.text.strip()}
            for index, paragraph in enumerate(word_document.paragraphs)
            if paragraph.text.strip()
        ]
        for table_index, table in enumerate(word_document.tables, start=1):
            for row_index, row in enumerate(table.rows, start=1):
                text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if text:
                    records.append({
                        "Section": f"Table {table_index}, row {row_index}",
                        "Text": text,
                    })
        if not records:
            raise ValueError("The Word document contains no readable text.")
        progress("indexing")
        result = capability.ingest_tabular(records, filename=filename, table_name=filename)
        element_count = len(records)

    stored = result.get("document") if isinstance(result, dict) else None
    document_id = stored.get("document_id") if isinstance(stored, dict) else None
    if not document_id:
        raise RuntimeError("Document ingestion did not return a document record.")
    if result.get("duplicate"):
        # The existing record already carries its own size/type/tags.
        return result

    progress("saving")
    metadata = RAGMetadataStore(user_id)
    with metadata.mutation_lock():
        record_data = metadata.get_document(document_id)
        if not record_data:
            raise RuntimeError("The ingested document could not be loaded.")
        record_data["size_bytes"] = written
        record_data["source_type"] = extension.lstrip(".")
        record_data["element_count"] = element_count
        chunks = metadata.load_chunks(document_id)
        sample_text = " ".join(chunk.page_content for chunk in chunks[:5])
        from insight_rag.service import _classify_document
        record_data["tags"] = _classify_document(filename, sample_text)
        metadata.put_document(record_data)
    result["document"] = record_data
    return result


def _ingestion_error_message(exc: BaseException) -> str:
    """Map an ingestion failure to the same client-safe text the sync route returns."""
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, (ValueError, RuntimeError)):
        return sanitize_error(exc)
    logging.getLogger(__name__).error("Document ingestion failed: %s", type(exc).__name__)
    return _INGEST_UNAVAILABLE


@router.post("/upload")
def upload_pdf(
    file: UploadFile = File(...),
    user: dict = Depends(require_writable),
):
    temp_path, filename, extension, written = _spool_upload(file)
    try:
        return _ingest_spooled(user["user_id"], temp_path, filename, extension, written)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=sanitize_error(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=sanitize_error(exc))
    except Exception:
        logging.getLogger(__name__).exception("Document ingestion failed for %s", extension)
        raise HTTPException(status_code=503, detail=_INGEST_UNAVAILABLE)
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/upload-batch", status_code=202)
def upload_documents_batch(
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_writable),
):
    """Accept several documents at once; each file becomes its own tracked job.

    A file that fails validation (type, size, empty) is reported as a failed
    job without stopping the rest of the batch. Progress is polled from
    GET /api/documents/upload-jobs?batch_id=... (general limiter, not the AI one).
    """
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one document to upload.")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Upload up to {MAX_BATCH_FILES} documents at a time.",
        )
    user_id = user["user_id"]
    batch_id = uuid.uuid4().hex
    jobs = []
    for upload in files:
        name = Path(upload.filename or "document").name
        try:
            temp_path, filename, extension, written = _spool_upload(upload)
        except HTTPException as exc:
            job = UPLOAD_JOBS.create(user_id, filename=name, size_bytes=0, batch_id=batch_id)
            jobs.append(UPLOAD_JOBS.fail(user_id, job["job_id"], str(exc.detail)))
            continue
        job = UPLOAD_JOBS.create(user_id, filename=filename, size_bytes=written, batch_id=batch_id)
        UPLOAD_JOBS.submit(
            user_id,
            job["job_id"],
            lambda progress, t=temp_path, f=filename, e=extension, w=written:
                _ingest_spooled(user_id, t, f, e, w, progress),
            on_error=_ingestion_error_message,
            cleanup=lambda t=temp_path: t.unlink(missing_ok=True),
        )
        jobs.append(job)
    return {"ok": True, "batch_id": batch_id, "jobs": jobs}


# Backwards-compatible name used by the upload-format tests/callers.
upload_document = upload_pdf


@router.get("/documents")
def list_pdf_documents(user: dict = Depends(get_current_user)):
    """List local PDF metadata without requiring a cloud LLM call."""
    documents = RAGMetadataStore(user["user_id"]).list_documents()
    public_docs = [
        {key: value for key, value in document.items()
         if key not in ("chunk_ids", "share_token", "shared_with", "shared")}
        for document in documents
    ]
    return {"ok": True, "documents": public_docs, "pipeline_version": RAG_PIPELINE_VERSION}


@router.delete("/documents/{document_id}")
def delete_pdf_document(document_id: str, user: dict = Depends(require_writable)):
    """Delete owned PDF metadata + vector chunks without constructing an LLM."""
    metadata = RAGMetadataStore(user["user_id"])
    with metadata.mutation_lock():
        record = metadata.get_document(document_id)
        if not record:
            raise HTTPException(status_code=404, detail="Document not found.")
        try:
            UserPGVectorStore(user["user_id"]).delete_chunks(record.get("chunk_ids", []))
            metadata.remove_document(document_id)
            metadata.document_file_path(document_id).unlink(missing_ok=True)
            metadata.chunks_path(document_id).unlink(missing_ok=True)
            return {"ok": True, "document_id": document_id}
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="I couldn't delete that PDF from the search index right now. Please try again.",
            )


@router.post("/chat")
def chat_with_pdfs(request: PDFChatRequest, user: dict = Depends(require_writable)):
    try:
        return _capability(user["user_id"]).chat(
            request.question,
            conversation_id=request.conversation_id,
            document_ids=request.document_ids,
            document_only=request.document_only,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=sanitize_error(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=sanitize_error(exc))
    except Exception:
        # Never expose raw SDK/network/database exceptions to the user-facing chat.
        raise HTTPException(
            status_code=503,
            detail="I'm having trouble with the PDF assistant right now. Your PDFs are safe; please try again in a moment.",
        )


def _public_message(message: dict) -> dict:
    """Conversation message for the client: internal routing metadata is dropped."""
    return {
        "role": message.get("role"),
        "content": message.get("content") or "",
        "sources": message.get("sources") or [],
        "created_at": message.get("created_at"),
    }


@router.get("/conversations")
def list_conversations(limit: int = Query(30, ge=1, le=100), user: dict = Depends(get_current_user)):
    """The user's document chats, most recent first (titles only, no bodies)."""
    return {"ok": True, "conversations": ConversationStore(user["user_id"]).summaries(limit)}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    store = ConversationStore(user["user_id"])
    try:
        if not store.exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        payload = store.load_recent(conversation_id, limit=80)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id.")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=sanitize_error(exc))
    return {
        "ok": True,
        "conversation": {
            "conversation_id": conversation_id,
            "title": payload.get("title"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "scope_document_ids": payload.get("scope_document_ids"),
            "messages": [_public_message(m) for m in payload.get("messages") or []],
        },
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: dict = Depends(require_writable)):
    store = ConversationStore(user["user_id"])
    try:
        with store.turn_lock(conversation_id):
            existed = store.delete(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id.")
    if not existed:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"ok": True, "conversation_id": conversation_id}
