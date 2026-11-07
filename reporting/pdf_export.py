"""Generate a downloadable PDF from a stored ARIA Intelligence report.

The same verified reporting payload powers the existing HTML export. This
module formats the supplied data; it never generates inferred statistics.
"""

from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


INK = colors.HexColor("#20342E")
ACCENT = colors.HexColor("#32614D")
SOFT = colors.HexColor("#EAF2ED")
MUTED = colors.HexColor("#5F7469")
PAGE_WIDTH, _ = A4
CONTENT_WIDTH = PAGE_WIDTH - 38 * mm


def _text(value: Any, limit: int = 1500) -> str:
    """Escape untrusted text before using ReportLab's paragraph markup."""
    if value is None:
        return ""
    return escape(str(value)[:limit], quote=True).replace("\n", "<br/>")


def render_intelligence_report_pdf(payload: dict) -> bytes:
    """Return paginated PDF bytes for an already authorized report payload."""
    payload = payload or {}
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=19 * mm, leftMargin=19 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=str(payload.get("title") or "ARIA Report")[:150],
        author="ARIA",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ARIA_Title", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=21, leading=27, textColor=INK, alignment=TA_LEFT,
        spaceAfter=5 * mm,
    )
    section = ParagraphStyle(
        "ARIA_Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=12, leading=16, textColor=ACCENT, spaceBefore=7 * mm,
        spaceAfter=3 * mm,
    )
    body = ParagraphStyle(
        "ARIA_Body", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.2, leading=14, textColor=INK, spaceAfter=2 * mm,
        splitLongWords=True,
    )
    small = ParagraphStyle(
        "ARIA_Muted", parent=body, fontSize=8, leading=12, textColor=MUTED,
    )
    cell = ParagraphStyle("ARIA_Cell", parent=body, fontSize=7.6, leading=11, spaceAfter=0)
    story = [
        Paragraph("ARIA / INTELLIGENCE REPORT", small),
        Spacer(1, 3 * mm),
        Paragraph(_text(payload.get("title") or "ARIA Report", 220), title),
    ]
    if payload.get("description"):
        story.append(Paragraph(_text(payload["description"], 1200), body))
    if payload.get("date_range"):
        story.append(Paragraph("Reporting period: " + _text(payload["date_range"], 180), small))
    story.extend([Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=1, color=SOFT)])

    sections = (payload.get("sections") or [])[:30]
    if sections:
        story.append(Paragraph("Included sections", section))
        for item in sections:
            if isinstance(item, dict):
                item = item.get("name") or item.get("title") or "Section"
            story.append(Paragraph("&#8226; " + _text(item, 150), body))

    findings = (payload.get("findings") or [])[:60]
    story.append(Paragraph("Findings", section))
    if not findings:
        story.append(Paragraph("No findings were available in the saved report.", small))
    for item in findings:
        if not isinstance(item, dict):
            continue
        label = item.get("title") or "Finding"
        detail = item.get("summary") or item.get("value_display") or ""
        item_flow = [Paragraph("<b>" + _text(label, 220) + "</b>", body)]
        if detail:
            item_flow.append(Paragraph(_text(detail, 800), small))
        story.append(KeepTogether(item_flow))

    for item in (payload.get("tables") or [])[:8]:
        if not isinstance(item, dict):
            continue
        cols = list(item.get("columns") or [])[:6]
        if not cols:
            continue
        story.append(Paragraph(_text(item.get("title") or "Data", 130), section))
        rows = [cols] + [list(row)[:len(cols)] for row in (item.get("rows") or [])[:45] if isinstance(row, (list, tuple))]
        grid = [
            [Paragraph(_text(val, 350), cell) for val in (row + [""] * len(cols))[:len(cols)]]
            for row in rows
        ]
        table = Table(grid, colWidths=[CONTENT_WIDTH / len(cols)] * len(cols), repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SOFT),
            ("TEXTCOLOR", (0, 0), (-1, 0), INK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, SOFT),
        ]))
        story.append(table)

    def footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(19 * mm, 12 * mm, "ARIA | Generated from stored report data")
        canvas.drawRightString(PAGE_WIDTH - 19 * mm, 12 * mm, f"Page {pdf_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
