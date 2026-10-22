"""PDF-RAG endpoints for ARIA's existing Industry Insight Agent.

RAG is an Insight Agent capability, not a fifth autonomous agent.
"""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

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
from insight_rag.storage import RAGMetadataStore, UserPGVectorStore
from llm_provider import create_provider

router = APIRouter(prefix="/api/insight/pdf", tags=["Insight PDF RAG"])
_DOCUMENT_MAX_UNPACKED_BYTES = 250 * 1024 * 1024
_DOCUMENT_MAX_ARCHIVE_ENTRIES = 20_000


class PDFChatRequest(BaseModel):
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
    ready = not config_error and provider_configured and database_configured
    return {
        "ok": True,
        "ready": ready,
        "status": "ready" if ready else "degraded",
        "pipeline_version": RAG_PIPELINE_VERSION,
        "model": RAG_LLM_MODEL if selected_provider == "deepseek" else None,
        "provider_name": selected_provider,
        "provider_configured": provider_configured,
        "database_configured": database_configured,
        "config_valid": config_error is None,
        "config_error": config_error,
        "documents": len(documents),
        "ingestion_quality": dict(quality_counts),
    }


@router.post("/upload")
def upload_pdf(
    file: UploadFile = File(...),
    user: dict = Depends(require_writable),
):
    filename = Path(file.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".csv", ".xlsx", ".docx"}:
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

        if extension == ".pdf":
            from insight_rag.ingestion import PDFIngestion
            return PDFIngestion(user["user_id"]).ingest_pdf(
                temp_path, original_filename=filename)

        capability = _capability(user["user_id"])
        element_count = 0
        if extension == ".csv":
            result = capability.ingest_tabular(temp_path, filename=filename, table_name=filename)
            element_count = int((result.get("document") or {}).get("row_count") or 0)
        elif extension == ".xlsx":
            _validate_office_archive(temp_path, "xl/workbook.xml")
            import pandas as pd

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
            result = capability.ingest_tabular(workbook, filename=filename, table_name=filename)
            element_count = int((result.get("document") or {}).get("row_count") or len(workbook))
        else:
            _validate_office_archive(temp_path, "word/document.xml")
            from docx import Document as WordDocument

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
            result = capability.ingest_tabular(records, filename=filename, table_name=filename)
            element_count = len(records)

        stored = result.get("document") if isinstance(result, dict) else None
        document_id = stored.get("document_id") if isinstance(stored, dict) else None
        if not document_id:
            raise RuntimeError("Document ingestion did not return a document record.")

        metadata = RAGMetadataStore(user["user_id"])
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
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=sanitize_error(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=sanitize_error(exc))
    except Exception:
        logging.getLogger(__name__).exception("Document ingestion failed for %s", extension)
        raise HTTPException(
            status_code=503,
            detail="I couldn't index that document right now. Please check the document and search service, then try again.",
        )
    finally:
        try:
            file.file.close()
        except Exception:
            pass
        if temp_path:
            temp_path.unlink(missing_ok=True)


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
