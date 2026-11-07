"""Text-based PDF ingestion with table preservation and extraction quality.

Supported scope:
- digitally generated/text PDFs
- normal paragraphs/headings
- tables extractable by pdfplumber

Scanned/image-only PDFs are deliberately rejected for now.  Every extracted
chunk is treated as untrusted evidence; instruction-like text is flagged for
observability but never executed as model instructions.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import TABLE_ROWS_PER_CHUNK, TEXT_CHUNK_OVERLAP, TEXT_CHUNK_SIZE
from .enterprise_quality import assess_ingestion_quality, scan_untrusted_instructions

_WHITESPACE_RE = re.compile(r"[ \t]+")


def _clean_text(text: str) -> str:
    lines = []
    for raw in (text or "").replace("\x00", " ").splitlines():
        line = _WHITESPACE_RE.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def _clean_cell(value) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value).replace("\n", " ")).strip()


def normalise_table(table: list[list]) -> list[list[str]]:
    rows = [[_clean_cell(cell) for cell in row] for row in (table or []) if row]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return []
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    keep_cols = [idx for idx in range(width) if any(row[idx] for row in padded)]
    return [[row[idx] for idx in keep_cols] for row in padded]


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    def esc(value: str) -> str:
        return value.replace("|", "\\|")

    header = rows[0]
    width = len(header)
    header = [cell or f"Column {i + 1}" for i, cell in enumerate(header)]
    body = [row + [""] * (width - len(row)) for row in rows[1:]]
    lines = [
        "| " + " | ".join(esc(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(esc(cell) for cell in row[:width]) + " |")
    return "\n".join(lines)


def _chunk_table(rows: list[list[str]], rows_per_chunk: int = TABLE_ROWS_PER_CHUNK) -> list[str]:
    if not rows:
        return []
    if len(rows) <= rows_per_chunk + 1:
        return [table_to_markdown(rows)]
    header = rows[0]
    body = rows[1:]
    return [
        table_to_markdown([header] + body[start : start + rows_per_chunk])
        for start in range(0, len(body), rows_per_chunk)
    ]


# Geometry-aware table handling ------------------------------------------------

TABLE_EXTRACTION_VERSION = "geometry_v1"
_BBOX_PAD = 2.0          # points; tolerance when masking text inside a table
_EDGE_FRACTION = 0.2     # a table "touches" a page edge within this band
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_NUMERIC_RE = re.compile(r"^[+-]?\(?[$£€₹]?\s*\d[\d,]*(?:\.\d+)?\s*%?\)?$")


def _is_numeric_cell(value: str) -> bool:
    return bool(_NUMERIC_RE.match((value or "").strip()))


def _row_is_header(row: list[str]) -> bool:
    """A first row is a header unless it carries data-like numbers.

    Year-like integers (e.g. 2023, 2024) are common column headings in
    financial tables, so they do not disqualify a header row.
    """
    cells = [cell.strip() for cell in row if cell and cell.strip()]
    if not cells:
        return False
    return not any(_is_numeric_cell(cell) and not _YEAR_RE.match(cell) for cell in cells)


def _with_header(rows: list[list[str]]) -> tuple[list[list[str]], bool]:
    """Ensure ``rows[0]`` is a header; synthesise one when the table has none."""
    if not rows:
        return rows, False
    if _row_is_header(rows[0]):
        return rows, True
    width = max(len(row) for row in rows)
    return [[f"Column {i + 1}" for i in range(width)]] + rows, False


def _inside(block_bbox, table_bbox) -> bool:
    x0, y0, x1, y1 = block_bbox
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    tx0, ty0, tx1, ty1 = table_bbox
    return (tx0 - _BBOX_PAD) <= cx <= (tx1 + _BBOX_PAD) and (ty0 - _BBOX_PAD) <= cy <= (ty1 + _BBOX_PAD)


def _page_text_outside_tables(fitz_page, table_bboxes: list[tuple]) -> str:
    """Page text with blocks that sit inside detected tables removed.

    Table content is indexed once, as a structured table chunk, instead of
    twice (once as flattened prose and once as a table).
    """
    blocks = fitz_page.get_text("blocks", sort=True) or []
    kept = []
    for block in blocks:
        if len(block) >= 7 and block[6] != 0:
            continue  # image block
        if any(_inside(block[:4], bbox) for bbox in table_bboxes):
            continue
        kept.append(str(block[4] or ""))
    return _clean_text("\n".join(kept))


def _detect_page_tables(plumber_page) -> list[dict]:
    """Tables with bounding boxes; falls back to bbox-less extraction."""
    found = []
    try:
        for table in plumber_page.find_tables() or []:
            rows = normalise_table(table.extract() or [])
            if len(rows) >= 2:
                found.append({"rows": rows, "bbox": tuple(float(v) for v in table.bbox)})
        return found
    except Exception:
        pass
    try:
        for raw in plumber_page.extract_tables() or []:
            rows = normalise_table(raw)
            if len(rows) >= 2:
                found.append({"rows": rows, "bbox": None})
    except Exception:
        return []
    return found


def _stitch_cross_page_tables(tables: list[dict]) -> list[dict]:
    """Join a table that continues at the top of the next page.

    A continuation is accepted only when the previous table ends in the
    bottom band of its page, the next one starts in the top band of the
    following page, and both have the same column count. A repeated header
    on the continuation is dropped; a header-less continuation is appended.
    """
    merged: list[dict] = []
    for table in tables:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous["bbox"] is not None and table["bbox"] is not None
            and table["page"] == previous["page_end"] + 1
            and table["index"] == 1
            and previous["last_on_page"]
            and previous["bbox"][3] >= previous["page_height"] * (1 - _EDGE_FRACTION)
            and table["bbox"][1] <= table["page_height"] * _EDGE_FRACTION
            and len(table["raw_rows"][0]) == len(previous["rows"][0])
        ):
            continuation = table["raw_rows"]
            if [c.casefold() for c in continuation[0]] == [c.casefold() for c in previous["rows"][0]]:
                continuation = continuation[1:]
            previous["rows"].extend(continuation)
            previous["page_end"] = table["page"]
            previous["last_on_page"] = table["last_on_page"]
            previous["bbox"] = table["bbox"]
            previous["page_height"] = table["page_height"]
            previous["stitched"] = True
            continue
        rows, header_detected = _with_header(table["raw_rows"])
        merged.append({**table, "rows": rows, "header_detected": header_detected,
                       "page_end": table["page"], "stitched": False,
                       "start_bbox": table["bbox"]})
    return merged


def _stable_chunk_id(document_id: str, kind: str, page: int, ordinal: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aria-pdf:{document_id}:{kind}:{page}:{ordinal}"))


def _security_metadata(text: str) -> dict:
    flags = scan_untrusted_instructions(text)
    return {
        "security_flags": flags,
        "contains_instruction_like_text": bool(flags),
    }


def extract_pdf_documents(
    pdf_path: str | Path,
    *,
    document_id: str,
    filename: str,
) -> tuple[list[Document], dict]:
    """Extract LangChain Documents plus an auditable ingestion-quality report."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Run: pip install pymupdf") from exc

    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required. Run: pip install pdfplumber") from exc

    path = Path(pdf_path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=TEXT_CHUNK_SIZE,
        chunk_overlap=TEXT_CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    text_chars = 0
    table_count = 0
    text_chunk_count = 0
    table_chunk_count = 0
    instruction_like_chunks = 0
    page_text_chars: list[int] = []
    text_by_page: dict[int, list[Document]] = {}
    detected_tables: list[dict] = []

    with fitz.open(path) as fitz_doc, pdfplumber.open(path) as plumber_doc:
        page_count = len(fitz_doc)
        if page_count > 500:
            raise ValueError("PDF exceeds the 500-page limit.")
        if fitz_doc.needs_pass:
            raise ValueError("Password-protected PDFs must be unlocked before uploading.")
        for page_index in range(page_count):
            page_number = page_index + 1
            fitz_page = fitz_doc[page_index]
            full_text = _clean_text(fitz_page.get_text("text"))
            # Quality/scan checks use the full page text, independent of masking.
            text_chars += len(full_text)
            page_text_chars.append(len(full_text))

            plumber_page = plumber_doc.pages[page_index]
            page_tables = _detect_page_tables(plumber_page)
            for table_index, table in enumerate(page_tables, start=1):
                detected_tables.append({
                    "page": page_number,
                    "index": table_index,
                    "raw_rows": table["rows"],
                    "bbox": table["bbox"],
                    "page_height": float(plumber_page.height or 0) or 1.0,
                    "last_on_page": table_index == len(page_tables),
                })

            bboxes = [table["bbox"] for table in page_tables if table["bbox"] is not None]
            page_text = _page_text_outside_tables(fitz_page, bboxes) if bboxes else full_text
            page_docs = text_by_page.setdefault(page_number, [])
            if page_text:
                for ordinal, chunk in enumerate(splitter.split_text(page_text)):
                    security = _security_metadata(chunk)
                    instruction_like_chunks += int(security["contains_instruction_like_text"])
                    page_docs.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                "document_id": document_id,
                                "filename": filename,
                                "page": page_number,
                                "content_type": "text",
                                "chunk_id": _stable_chunk_id(document_id, "text", page_number, ordinal),
                                **security,
                            },
                        )
                    )
                    text_chunk_count += 1

    tables_by_page: dict[int, list[Document]] = {}
    for table in _stitch_cross_page_tables(detected_tables):
        rows = table["rows"]
        table_count += 1
        table_chunks = _chunk_table(rows)
        page_number, table_index = table["page"], table["index"]
        for ordinal, table_text in enumerate(table_chunks):
            if not table_text.strip():
                continue
            security = _security_metadata(table_text)
            instruction_like_chunks += int(security["contains_instruction_like_text"])
            metadata = {
                "document_id": document_id,
                "filename": filename,
                "page": page_number,
                "content_type": "table",
                "table_index": table_index,
                "table_chunk_index": ordinal,
                "table_chunk_count": len(table_chunks),
                "table_row_count": len(rows) - 1,
                "table_header_detected": bool(table["header_detected"]),
                "table_extraction": TABLE_EXTRACTION_VERSION,
                "chunk_id": _stable_chunk_id(
                    document_id, f"table-{table_index}", page_number, ordinal
                ),
                **security,
            }
            if table["start_bbox"] is not None:
                metadata["table_bbox"] = [round(v, 1) for v in table["start_bbox"]]
            if table["stitched"]:
                metadata["page_end"] = table["page_end"]
            tables_by_page.setdefault(page_number, []).append(
                Document(page_content=table_text, metadata=metadata))
            table_chunk_count += 1

    # Keep the historical order: each page's text chunks, then its tables.
    documents: list[Document] = []
    for page_number in range(1, page_count + 1):
        documents.extend(text_by_page.get(page_number, []))
        documents.extend(tables_by_page.get(page_number, []))

    if text_chars < max(80, page_count * 20):
        raise ValueError(
            "This PDF appears to be scanned/image-only or has too little extractable text. "
            "The current Insight RAG version supports text-based PDFs only."
        )
    if not documents:
        raise ValueError("No usable text or tables could be extracted from this PDF.")

    quality = assess_ingestion_quality(
        pages=page_count,
        text_chars=text_chars,
        page_text_chars=page_text_chars,
        tables=table_count,
        instruction_like_chunks=instruction_like_chunks,
    )

    return documents, {
        "pages": page_count,
        "text_chars": text_chars,
        "page_text_chars": page_text_chars,
        "tables": table_count,
        "text_chunks": text_chunk_count,
        "table_chunks": table_chunk_count,
        "total_chunks": len(documents),
        "instruction_like_chunks": instruction_like_chunks,
        "ingestion_quality": quality,
    }
