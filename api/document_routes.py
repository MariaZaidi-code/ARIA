"""Document API routes: upload, list, search, retrieve, delete."""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import List, Optional

from core.config import PROCESSED_DIR, get_session
from core.deps import require_writable, get_current_user
from document_processor import create_document_processor

router = APIRouter()


class DocumentSearchRequest(BaseModel):
    query: str
    document_ids: Optional[List[str]] = None
    k: int = 10


class DocumentSearchResponse(BaseModel):
    ok: bool
    results: List[dict]


@router.get("/api/documents")
def list_documents(
    request: Request,
    user: dict = Depends(get_current_user),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List user's uploaded documents."""
    session = get_session(user["user_id"])
    # For now, we'll scan the processed directory
    # In production, this would query a documents table
    
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    if not processed_dir.exists():
        return {"ok": True, "documents": []}
    
    documents = []
    for doc_file in processed_dir.glob("*.json"):
        try:
            import json
            doc_data = json.loads(doc_file.read_text())
            if status and doc_data.get("status") != status:
                continue
            documents.append({
                "id": doc_data.get("id"),
                "name": doc_data.get("original_name"),
                "file_size": doc_data.get("file_size"),
                "page_count": doc_data.get("page_count"),
                "document_type": doc_data.get("document_type"),
                "status": doc_data.get("status"),
                "created_at": doc_data.get("created_at"),
                "completed_at": doc_data.get("completed_at"),
                "element_count": doc_data.get("element_count", 0),
                "chunk_count": doc_data.get("chunk_count", 0),
                "table_count": doc_data.get("table_count", 0),
                "processing_method": doc_data.get("processing_method"),
                "error_message": doc_data.get("error_message"),
            })
        except Exception:
            continue
    
    # Sort by created_at descending
    documents.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    
    return {"ok": True, "documents": documents[:limit]}


@router.get("/api/documents/{document_id}")
def get_document(
    document_id: str,
    user: dict = Depends(get_current_user),
):
    """Get document details."""
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    doc_file = processed_dir / f"{document_id}.json"
    
    if not doc_file.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    
    import json
    doc_data = json.loads(doc_file.read_text())
    
    # Verify ownership
    if doc_data.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {"ok": True, "document": doc_data}


@router.post("/api/documents/{document_id}/search")
def search_document(
    document_id: str,
    request: DocumentSearchRequest,
    user: dict = Depends(get_current_user),
):
    """Search within a specific document using RAG."""
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    doc_file = processed_dir / f"{document_id}.json"
    
    if not doc_file.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    
    import json
    doc_data = json.loads(doc_file.read_text())
    
    if doc_data.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Create processor for search
    processor = create_document_processor(
        upload_dir="data/uploads",
        processed_dir=PROCESSED_DIR / f"user_{user['user_id']}" / "documents",
    )
    
    results = processor.get_document_context(
        document_id=document_id,
        query=request.query,
        k=request.k,
    )
    
    return {
        "ok": True,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "score": r.score,
                "page_number": r.page_number,
                "section": r.section,
                "metadata": r.metadata,
            }
            for r in results
        ],
    }


@router.post("/api/documents/search")
def search_all_documents(
    request: DocumentSearchRequest,
    user: dict = Depends(get_current_user),
):
    """Search across all user's documents using RAG."""
    processor = create_document_processor(
        upload_dir="data/uploads",
        processed_dir=PROCESSED_DIR / f"user_{user['user_id']}" / "documents",
    )
    
    results = processor.search_documents(
        query=request.query,
        user_id=user["user_id"],
        document_ids=request.document_ids,
        k=request.k,
    )
    
    return {
        "ok": True,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
                "content": r.content,
                "score": r.score,
                "page_number": r.page_number,
                "section": r.section,
                "metadata": r.metadata,
            }
            for r in results
        ],
    }


@router.delete("/api/documents/{document_id}")
def delete_document(
    document_id: str,
    user: dict = Depends(require_writable),
):
    """Delete a document and its associated data."""
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    doc_file = processed_dir / f"{document_id}.json"
    
    if not doc_file.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    
    import json
    doc_data = json.loads(doc_file.read_text())
    
    if doc_data.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Create processor for deletion
    processor = create_document_processor(
        upload_dir="data/uploads",
        processed_dir=processed_dir,
    )
    
    success = processor.delete_document(document_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete document")
    
    # Also delete the uploaded file if it exists
    upload_dir = Path("data/uploads")
    for upload_file in upload_dir.glob(f"*{document_id}*"):
        upload_file.unlink(missing_ok=True)
    
    return {"ok": True, "message": "Document deleted"}


@router.post("/api/documents/{document_id}/retry")
def retry_document(
    document_id: str,
    user: dict = Depends(require_writable),
):
    """Retry processing a failed document."""
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    doc_file = processed_dir / f"{document_id}.json"
    
    if not doc_file.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    
    import json
    doc_data = json.loads(doc_file.read_text())
    
    if doc_data.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc_data.get("status") not in ("failed", "partial"):
        raise HTTPException(status_code=400, detail="Document is not in a failed state")
    
    # Get the original file
    upload_dir = Path("data/uploads")
    file_path = None
    for f in upload_dir.glob(f"*{doc_data.get('original_name', '')}*"):
        if f.suffix.lower() == ".pdf":
            file_path = f
            break
    
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Original file not found for retry")
    
    # Get session for LLM provider
    session = get_session(user["user_id"])
    llm = session.get("provider")
    
    # Create processor and reprocess
    processor = create_document_processor(
        upload_dir=upload_dir,
        processed_dir=processed_dir,
        llm_provider=llm,
    )
    
    result = processor.process_document(
        file_path=file_path,
        document_id=document_id,
        user_id=user["user_id"],
        original_name=doc_data.get("original_name"),
    )
    
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Retry failed")
    
    return {
        "ok": True,
        "document": result.document.to_dict() if hasattr(result.document, 'to_dict') else result.document.__dict__,
    }