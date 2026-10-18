"""Story export API: turn an answer envelope into PPTX / XLSX / print HTML.

The frontend posts the exact envelope it already displays (question, answer,
story, drivers, hypothesis, columns/rows, sql, as-of). Nothing is recomputed
here — exports render the same grounded content the user sees, so no number
in a deck can drift from the app.

No server-side PDF engine is installed by design: the HTML export is a
self-contained, print-ready page (browsers "Print to PDF" losslessly), while
PPTX and XLSX are generated natively.
"""

from __future__ import annotations

import html as _html
import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from core.deps import require_writable

router = APIRouter(prefix="/api/export", tags=["export"])

_MAX_ROWS = 500
_MAX_SLIDE_ROWS = 25


class StoryExport(BaseModel):
    format: str = "html"
    question: str = ""
    answer: str = ""
    story: str = ""
    why: str = ""
    hypothesis: str = ""
    drivers: list[dict] = []
    columns: list[str] = []
    rows: list[dict] = []
    sql: str = ""
    as_of: str = ""
    dataset: str = ""
    include_sql: bool = False

    model_config = ConfigDict(extra="allow")


def _slug(text: str, fallback: str = "aria-story") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "")).strip("-").lower()
    return (s[:60] or fallback)


def _to_float(v):
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fmt(v) -> str:
    f = _to_float(v)
    if f is None:
        return "—" if v is None else str(v)
    a = abs(f)
    if a >= 1_000_000:
        return f"{f / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{f / 1_000:.1f}K"
    if a >= 10:
        return f"{f:,.0f}"
    return f"{f:,.2f}".rstrip("0").rstrip(".")


def _fmt_pct(v) -> str:
    f = _to_float(v)
    if f is None:
        return "—"
    return f"{f:.1f}".rstrip("0").rstrip(".")


def _measure_column(columns: list[str], rows: list[dict]) -> str | None:
    for c in reversed(columns):
        vals = [_to_float(r.get(c)) for r in rows[:20] if r.get(c) is not None]
        if vals and all(v is not None for v in vals):
            return c
    for c in columns:
        vals = [_to_float(r.get(c)) for r in rows[:20] if r.get(c) is not None]
        if any(v is not None for v in vals):
            return c
    return None


def _category_column(columns: list[str], rows: list[dict],
                     measure: str | None) -> str | None:
    for c in columns:
        if c == measure:
            continue
        if all(_to_float(r.get(c)) is None for r in rows[:20] if r.get(c) is not None):
            return c
    return columns[0] if columns else None


def _title(payload: StoryExport) -> str:
    return (payload.question or payload.answer or "ARIA analysis").strip()[:180]


def _meta_line(payload: StoryExport) -> str:
    bits = []
    if payload.dataset:
        bits.append(str(payload.dataset)[:120])
    bits.append(f"as of {payload.as_of}" if payload.as_of else
                "as of " + datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return " · ".join(bits)


def _driver_lines(payload: StoryExport) -> list[str]:
    out = []
    for d in payload.drivers[:12]:
        if not isinstance(d, dict):
            continue
        label = str(d.get("label") or d.get("name") or d.get("dimension") or "").strip()
        value = d.get("value")
        delta = d.get("delta")
        contrib = d.get("contribution_pct")
        parts = [label] if label else []
        if value is not None:
            parts.append(_fmt(value))
        if delta is not None:
            parts.append(f"Δ {_fmt(delta)}")
        if contrib is not None:
            parts.append(f"{_fmt_pct(contrib)}% of change")
        if parts:
            out.append(" — ".join(parts[:1]) + (" (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else ""))
    return out


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

def _pptx_bytes(payload: StoryExport) -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    ink = RGBColor(0x1A, 0x1A, 0x2E)
    accent = RGBColor(0x5B, 0x5B, 0xD6)

    def add_title(slide, text, top=Inches(0.45), size=30):
        box = slide.shapes.add_textbox(Inches(0.6), top,
                                       prs.slide_width - Inches(1.2), Inches(1.0))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(size)
        p.font.bold = True
        p.font.color.rgb = ink
        return box

    def add_body(slide, lines, top, size=16, left=Inches(0.6), width=None):
        box = slide.shapes.add_textbox(
            left, top, (width or (prs.slide_width - Inches(1.2))), Inches(5))
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for line in lines:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.text = line
            p.font.size = Pt(size)
            p.font.color.rgb = ink
            p.space_after = Pt(8)
        return box

    def footer(slide, text):
        box = slide.shapes.add_textbox(Inches(0.6), prs.slide_height - Inches(0.5),
                                       prs.slide_width - Inches(1.2), Inches(0.35))
        p = box.text_frame.paragraphs[0]
        p.text = text
        p.font.size = Pt(9)
        p.font.color.rgb = RGBColor(0x88, 0x88, 0x99)

    # Slide 1 — title + answer
    s = prs.slides.add_slide(blank)
    add_title(s, _title(payload), top=Inches(2.2), size=34)
    lines = []
    if payload.answer:
        lines.append(payload.answer.strip()[:600])
    lines.append(_meta_line(payload))
    add_body(s, lines, Inches(3.6), size=16)

    # Slide 2 — story / why
    story_bits = [b for b in (payload.story, payload.why, payload.hypothesis) if b]
    if story_bits:
        s = prs.slides.add_slide(blank)
        add_title(s, "What happened", size=26)
        lines = []
        for b in story_bits:
            lines.extend([ln.strip() for ln in str(b).splitlines() if ln.strip()])
        add_body(s, lines[:12], Inches(1.6), size=16)
        footer(s, _meta_line(payload))

    # Slide 3 — drivers
    drivers = _driver_lines(payload)
    if drivers:
        s = prs.slides.add_slide(blank)
        add_title(s, "Drivers of the change", size=26)
        add_body(s, drivers, Inches(1.6), size=16)
        footer(s, _meta_line(payload))

    # Slide 4 — native chart (if tabular numeric data exists)
    cols = [str(c) for c in (payload.columns or [])][:40]
    rows = [r for r in (payload.rows or []) if isinstance(r, dict)][:_MAX_SLIDE_ROWS]
    measure = _measure_column(cols, rows) if cols and rows else None
    cat = _category_column(cols, rows, measure) if measure else None
    if measure and cat and rows:
        s = prs.slides.add_slide(blank)
        add_title(s, f"{measure} by {cat}", size=24)
        chart_data = CategoryChartData()
        chart_data.categories = [str(r.get(cat) or "")[:40] for r in rows]
        chart_data.add_series(str(measure)[:40],
                              tuple(_to_float(r.get(measure)) or 0.0 for r in rows))
        gframe = s.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.5),
            prs.slide_width - Inches(1.2), prs.slide_height - Inches(2.3), chart_data)
        chart = gframe.chart
        chart.has_legend = False
        try:
            plot = chart.plots[0]
            plot.has_data_labels = len(rows) <= 12
            series_fill = plot.series[0].format.fill
            series_fill.solid()
            series_fill.fore_color.rgb = accent
        except Exception:
            pass
        footer(s, _meta_line(payload))

    # Final slide — table + optional SQL
    if cols and rows:
        s = prs.slides.add_slide(blank)
        add_title(s, "Data", size=24)
        show_cols = cols[:8]
        tbl = s.shapes.add_table(len(rows[:12]) + 1, len(show_cols),
                                 Inches(0.5), Inches(1.4),
                                 prs.slide_width - Inches(1.0),
                                 min(Inches(5.2), Emu(int(Inches(0.32)) * (len(rows[:12]) + 1)))
                                 ).table
        for j, c in enumerate(show_cols):
            cell = tbl.cell(0, j)
            cell.text = c[:30]
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(11)
                    run.font.bold = True
        for i, r in enumerate(rows[:12], start=1):
            for j, c in enumerate(show_cols):
                cell = tbl.cell(i, j)
                v = r.get(c)
                cell.text = (str(v) if _to_float(v) is None else _fmt(v))[:40]
                for para in cell.text_frame.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(10)
        footer(s, _meta_line(payload))

    if payload.include_sql and payload.sql:
        s = prs.slides.add_slide(blank)
        add_title(s, "Underlying query", size=22)
        add_body(s, [str(payload.sql)[:1600]], Inches(1.6), size=11)
        footer(s, _meta_line(payload))

    bio = io.BytesIO()
    prs.save(bio)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def _xlsx_bytes(payload: StoryExport, sql_included: bool) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="EEF0FF")

    def section(title: str) -> None:
        ws.append([])
        ws.append([title])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)

    ws.append(["ARIA story export"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")])
    ws.append(["As of", payload.as_of or ""])
    ws.append(["Dataset", payload.dataset or ""])
    ws.append(["Question", payload.question or ""])
    ws.append(["Answer", payload.answer or ""])
    if payload.story:
        section("Story")
        for line in str(payload.story).splitlines():
            if line.strip():
                ws.append([line.strip()])
    if payload.why:
        section("Why")
        for line in str(payload.why).splitlines():
            if line.strip():
                ws.append([line.strip()])
    if payload.hypothesis:
        section("Hypothesis")
        for line in str(payload.hypothesis).splitlines():
            if line.strip():
                ws.append([line.strip()])
    drivers = _driver_lines(payload)
    if drivers:
        section("Drivers")
        for line in drivers:
            ws.append([line])
    if sql_included and payload.sql:
        section("SQL")
        ws.append([str(payload.sql)[:32000]])

    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 80

    cols = [str(c) for c in (payload.columns or [])][:60]
    rows = [r for r in (payload.rows or []) if isinstance(r, dict)][:_MAX_ROWS]
    if cols and rows:
        ds = wb.create_sheet("Data")
        ds.append(cols)
        for j in range(1, len(cols) + 1):
            c = ds.cell(row=1, column=j)
            c.font = bold
            c.fill = header_fill
        for r in rows:
            ds.append([r.get(c) if _to_float(r.get(c)) is None else _to_float(r.get(c))
                       for c in cols])
        ds.freeze_panes = "A2"
        for idx, c in enumerate(cols, start=1):
            width = min(40, max(12, len(c) + 4))
            ds.column_dimensions[ds.cell(row=1, column=idx).column_letter].width = width

    # openpyxl interprets strings beginning with '=' as formulas. All values
    # in this export are user/data content, so keep strings literal in Excel.
    for sheet in wb.worksheets:
        for cell_row in sheet.iter_rows():
            for cell in cell_row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# Print-ready HTML
# ---------------------------------------------------------------------------

def _html_bytes(payload: StoryExport, sql_included: bool) -> bytes:
    e = _html.escape
    cols = [str(c) for c in (payload.columns or [])][:60]
    rows = [r for r in (payload.rows or []) if isinstance(r, dict)][:_MAX_ROWS]
    measure = _measure_column(cols, rows) if cols and rows else None
    cat = _category_column(cols, rows, measure) if measure else None

    parts: list[str] = []
    parts.append(f"<h1>{e(_title(payload))}</h1>")
    parts.append(f"<p class='meta'>{e(_meta_line(payload))}</p>")
    if payload.answer:
        parts.append(f"<div class='answer'>{e(payload.answer.strip())}</div>")
    if payload.story:
        parts.append("<h2>What happened</h2>" + "".join(
            f"<p>{e(ln.strip())}</p>" for ln in str(payload.story).splitlines() if ln.strip()))
    if payload.why:
        parts.append("<h2>Why</h2>" + "".join(
            f"<p>{e(ln.strip())}</p>" for ln in str(payload.why).splitlines() if ln.strip()))
    if payload.hypothesis:
        parts.append(f"<h2>Hypothesis</h2><p>{e(payload.hypothesis.strip())}</p>")
    drivers = payload.drivers[:12]
    dl = _driver_lines(payload)
    if dl:
        parts.append("<h2>Drivers of the change</h2><ul>" + "".join(
            f"<li>{e(line)}</li>" for line in dl) + "</ul>")
        maxc = max((abs(_to_float(d.get('contribution_pct')) or 0) for d in drivers
                    if isinstance(d, dict)), default=0) or 1
        bars = []
        for d in drivers:
            if not isinstance(d, dict):
                continue
            label = str(d.get("label") or d.get("name") or d.get("dimension") or "")
            c = _to_float(d.get("contribution_pct"))
            if c is None:
                continue
            pct = min(100.0, abs(c) / maxc * 100.0)
            bars.append(
                f"<div class='bar-row'><span class='bar-label'>{e(label[:40])}</span>"
                f"<span class='bar' style='width:{pct:.1f}%'></span>"
                f"<span class='bar-val'>{e(_fmt_pct(c))}%</span></div>")
        if bars:
            parts.append("<div class='bars'>" + "".join(bars) + "</div>")
    if cols and rows:
        parts.append("<h2>Data</h2><table><thead><tr>" + "".join(
            f"<th>{e(c)}</th>" for c in cols) + "</tr></thead><tbody>")
        for r in rows[:200]:
            parts.append("<tr>" + "".join(
                f"<td>{e(str(r.get(c)) if _to_float(r.get(c)) is None else _fmt(r.get(c)))}</td>"
                for c in cols) + "</tr>")
        parts.append("</tbody></table>")
        if len(rows) > 200:
            parts.append(f"<p class='meta'>Showing 200 of {len(rows)} rows.</p>")
    if sql_included and payload.sql:
        parts.append("<h2>Underlying query</h2><pre>" + e(str(payload.sql)[:8000]) + "</pre>")

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{e(_title(payload))}</title>
<style>
:root {{ color-scheme: light; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; color: #1a1a2e;
  max-width: 960px; margin: 32px auto; padding: 0 24px; }}
h1 {{ font-size: 28px; margin-bottom: 4px; }}
h2 {{ font-size: 18px; margin-top: 28px; border-bottom: 1px solid #e3e3f0;
  padding-bottom: 6px; }}
p {{ line-height: 1.5; }}
.meta {{ color: #77778a; font-size: 12px; }}
.answer {{ font-size: 17px; background: #f4f4ff; border-left: 4px solid #5b5bd6;
  padding: 12px 16px; border-radius: 6px; }}
.bars {{ margin-top: 8px; }}
.bar-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.bar-label {{ width: 220px; font-size: 13px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }}
.bar {{ height: 14px; background: linear-gradient(90deg,#5b5bd6,#8f8ff0);
  border-radius: 4px; min-width: 2px; }}
.bar-val {{ font-size: 12px; color: #55556b; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 12.5px; }}
th, td {{ border: 1px solid #e3e3f0; padding: 6px 10px; text-align: left; }}
th {{ background: #eef0ff; }}
pre {{ background: #f6f6fb; padding: 12px; border-radius: 6px; overflow-x: auto;
  font-size: 12px; }}
@media print {{ body {{ margin: 0 auto; }} h2 {{ break-after: avoid; }}
  tr {{ break-inside: avoid; }} }}
</style></head><body>
{''.join(parts)}
<hr><p class='meta'>Generated by ARIA. Numbers are reproduced exactly from the
in-app answer — nothing is recomputed at export time.</p>
</body></html>"""
    return doc.encode("utf-8")


_MEDIA = {
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "html": ("text/html; charset=utf-8", "html"),
}


@router.post("/story")
def export_story(req: StoryExport, request: Request,
                 user: dict = Depends(require_writable)):
    """Export an answer envelope as PPTX, XLSX, or print-ready HTML."""
    fmt = str(req.format or "html").strip().lower()
    if fmt not in _MEDIA:
        raise HTTPException(status_code=422,
                            detail="Format must be one of: pptx, xlsx, html.")
    sql_included = bool(req.include_sql)
    try:
        if fmt == "pptx":
            data = _pptx_bytes(req)
        elif fmt == "xlsx":
            data = _xlsx_bytes(req, sql_included)
        else:
            data = _html_bytes(req, sql_included)
    except ImportError as exc:
        # Optional renderer missing (e.g. openpyxl / python-pptx not
        # installed): degrade with a clear, actionable status instead of an
        # opaque 500. HTML export needs no third-party dependency.
        raise HTTPException(
            status_code=501,
            detail=(f"{fmt.upper()} export is unavailable: the optional "
                    f"'{getattr(exc, 'name', 'renderer')}' dependency is not "
                    "installed. Use HTML export or install the package."),
        )
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"Export failed: {type(exc).__name__}.")
    filename = f"{_slug(req.question or req.answer)}.{_MEDIA[fmt][1]}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(data), media_type=_MEDIA[fmt][0],
                             headers=headers)
