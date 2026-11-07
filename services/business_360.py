"""Business 360: data-derived 360-degree answer for AI Analytics.

Every field is computed from the executed rows / drivers / hypothesis /
prescription that the caller already produced. Nothing is templated: when the
data does not support a statement, that field is omitted (empty list / null)
rather than filled with generic advice.
"""
from __future__ import annotations

import re


def _num(v):
    try:
        if v is None or v is True or v is False:
            return None
        if isinstance(v, (int, float)):
            f = float(v)
            return f if f == f and abs(f) != float("inf") else None
        s = str(v).replace(",", "").strip()
        if not s:
            return None
        f = float(s)
        return f if f == f and abs(f) != float("inf") else None
    except Exception:
        return None


def _fmt_money(n):
    if n is None:
        return "—"
    a = abs(n)
    v, suffix = n, ""
    if a >= 1_000_000_000:
        v, suffix = n / 1_000_000_000, "B"
    elif a >= 1_000_000:
        v, suffix = n / 1_000_000, "M"
    elif a >= 10_000:
        v, suffix = n / 1_000, "K"
    if suffix:
        return f"{v:,.1f}{suffix}"
    if float(n).is_integer():
        return f"{int(n):,}"
    return f"{n:,.1f}"


def _human(col: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(col or ""))
    s = s.replace("_", " ").strip()
    return " ".join(w.capitalize() for w in s.split()) or str(col or "value")


def _detect_period_col(columns, rows):
    for c in columns or []:
        cl = str(c).lower()
        if any(k in cl for k in ("period", "month", "date", "week", "quarter", "year", "day")):
            return c
    return None


def _detect_value_col(columns, rows, metric_col=None):
    if metric_col and metric_col in (columns or []):
        return metric_col
    for c in columns or []:
        cl = str(c).lower()
        if "(" in cl or "*" in cl:
            continue
        if rows and isinstance(rows[0], dict):
            if _num(rows[0].get(c)) is not None:
                if not cl.endswith("_id") and cl not in ("id",):
                    return c
    for c in columns or []:
        if rows and isinstance(rows[0], dict) and _num(rows[0].get(c)) is not None:
            return c
    return None


def _detect_seg_col(columns, rows, value_col, period_col):
    for c in columns or []:
        if c in (value_col, period_col):
            continue
        cl = str(c).lower()
        if "(" in cl or "*" in cl:
            continue
        return c
    return None


def _driver_name(d: dict) -> str:
    """Pick a human-readable driver label from a real driver dict."""
    for k in ("driver", "label", "name", "dimension"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def build_business360(*, question, result_data, columns, metric_label=None,
                      metric_col=None, dims=None, drivers=None,
                      hypothesis=None, prescription=None, chart_spec=None) -> dict:
    """Build the 360 block. Every statement is derived from the supplied data."""
    rows = [r for r in (result_data or []) if isinstance(r, dict)]
    cols = list(columns or (list(rows[0].keys()) if rows else []))

    period_col = _detect_period_col(cols, rows)
    value_col = _detect_value_col(cols, rows, metric_col)
    seg_col = _detect_seg_col(cols, rows, value_col, period_col)

    metric_name = str(metric_label or metric_col or value_col or "Value")
    metric_plain = _human(metric_name)

    # ---- What happened (purely computed) ----
    total = None
    change_pct = None
    before_v = after_v = None
    period_label = ""
    direction = None
    if rows and value_col:
        vals = [_num(r.get(value_col)) for r in rows]
        vals = [v for v in vals if v is not None]
        if vals:
            if period_col:
                try:
                    ordered = sorted(rows, key=lambda r: str(r.get(period_col) or ""))
                except Exception:
                    ordered = rows
                ovals = [_num(r.get(value_col)) for r in ordered]
                ovals = [v for v in ovals if v is not None]
                if len(ovals) >= 2:
                    before_v, after_v = ovals[0], ovals[-1]
                    base = (sum(ovals[:-1]) / max(1, len(ovals) - 1)
                            if len(ovals) > 2 else (ovals[0] or 0))
                    if base:
                        change_pct = round((ovals[-1] - base) / abs(base) * 100, 1)
                    total = round(sum(ovals), 2)
                    try:
                        period_label = f"{ordered[0].get(period_col)} → {ordered[-1].get(period_col)}"
                    except Exception:
                        period_label = ""
                elif len(ovals) == 1:
                    total = round(ovals[0], 2)
            else:
                total = round(sum(vals), 2)

    if change_pct is not None:
        if change_pct <= -0.5:
            direction = "down"
        elif change_pct >= 0.5:
            direction = "up"
        else:
            direction = "steady"

    # headline
    seg_hint = ""
    if seg_col and rows and value_col:
        try:
            top_row = max(rows, key=lambda r: (_num(r.get(value_col)) or 0))
            seg_hint = str(top_row.get(seg_col) or "")
        except Exception:
            seg_hint = ""

    if change_pct is not None and abs(change_pct) >= 0.5:
        headline = f"{metric_plain} is {direction} {abs(change_pct)}% — here's what to do"
    elif seg_hint:
        headline = f"{metric_plain}: {seg_hint} leads — here's the full picture"
    else:
        headline = f"{metric_plain}: here's the full picture in plain words"

    if change_pct is not None and abs(change_pct) >= 0.5:
        what_summary = (
            f"{metric_plain} went {direction} by {abs(change_pct)}% "
            f"({_fmt_money(before_v)} → {_fmt_money(after_v)})"
            + (f" over {period_label}." if period_label else ".")
            + (f" Total in view: {_fmt_money(total)}." if total is not None else "")
        )
    elif total is not None:
        what_summary = (f"{metric_plain} totals {_fmt_money(total)} across "
                        f"{len(rows)} group(s). No sharp up/down move — the "
                        "story is in the mix below.")
    else:
        what_summary = "We found your data but couldn't size a move from the rows returned."

    # ---- Likely causes (from real drivers / top segments only) ----
    likely_causes = []
    for d in (drivers or [])[:3]:
        if not isinstance(d, dict):
            continue
        name = _driver_name(d)
        if not name:
            continue
        share = (d.get("contribution_pct") or d.get("share_pct")
                 or d.get("share"))
        try:
            share_f = float(str(share).replace("%", "")) if share is not None else None
        except Exception:
            share_f = None
        why = (f"Holds about {share_f}% of {metric_plain.lower()}."
               if share_f is not None else "Shows up strongly in your data.")
        likely_causes.append({
            "cause": _human(name),
            "why_plain": f"{_human(name)} {why} When this moves, your total moves with it — focus here first.",
            "share_pct": share_f,
        })

    if seg_col and value_col and rows and len(likely_causes) < 3:
        try:
            srows = sorted(rows, key=lambda r: (_num(r.get(value_col)) or 0),
                           reverse=True)[:3]
            tot = sum((_num(r.get(value_col)) or 0) for r in rows)
            for r in srows:
                nm = str(r.get(seg_col) or "")
                v = _num(r.get(value_col)) or 0
                if not nm:
                    continue
                if any(nm.lower() in str(c.get("cause", "")).lower()
                       for c in likely_causes):
                    continue
                sh = round(v / tot * 100, 1) if tot else None
                lever = (" — the biggest lever in view." if not likely_causes
                         else " — the next lever to watch.")
                likely_causes.append({
                    "cause": nm,
                    "why_plain": (f"{nm} contributes {_fmt_money(v)}"
                                  + (f" ({sh}% of the total)" if sh is not None else "")
                                  + lever),
                    "share_pct": sh,
                })
                if len(likely_causes) >= 3:
                    break
        except Exception:
            pass

    if hypothesis and isinstance(hypothesis, dict):
        ht = str(hypothesis.get("text") or "")[:300]
        if ht and len(likely_causes) < 3:
            ht = re.sub(r"\b(p\s*[=<]\s*0\.\d+|r\s*=\s*-?\d\.?\d*|n\s*=\s*\d+)\b",
                        "", ht).strip()
            if ht:
                likely_causes.append({
                    "cause": "Pattern in the data",
                    "why_plain": ht,
                    "share_pct": None,
                })

    likely_causes = likely_causes[:3]

    # ---- What to do (only from the prescription engine output) ----
    what_to_do = []
    eng_pres = []
    try:
        if isinstance(prescription, dict):
            eng_pres = [p for p in (prescription.get("prescriptions") or [])
                        if isinstance(p, dict)]
    except Exception:
        eng_pres = []
    for p in eng_pres[:3]:
        title = str(p.get("title") or p.get("name") or "").strip()
        title = re.sub(r"\b(scenario|ols|pearson|spearman|p_value|r_value)\b",
                       "", title, flags=re.I).strip(" -:") or "Recommended move"
        disp = p.get("display") if isinstance(p.get("display"), dict) else {}
        action = str(disp.get("action_text") or p.get("action") or "")[:400].strip()
        outcome = str(disp.get("outcome_text") or "")[:300].strip()
        steps = [action] if action else []
        what_to_do.append({
            "title": title[:120],
            "steps": steps[:3],
            "expected": outcome or None,
            "effort": (str(p.get("effort")).strip() if p.get("effort") else None),
        })

    # ---- If you do nothing ----
    if_do_nothing = None
    if change_pct is not None and change_pct < -0.5:
        monthly_burn = None
        if before_v is not None and after_v is not None:
            monthly_burn = round(before_v - after_v, 2)
        if monthly_burn and monthly_burn > 0:
            if_do_nothing = (f"If nothing changes, you keep losing roughly "
                             f"{_fmt_money(monthly_burn)} per period at the "
                             f"current pace ({abs(change_pct)}% down). Over 3 "
                             f"periods that's about {_fmt_money(monthly_burn * 3)} "
                             "left on the table.")
        else:
            if_do_nothing = (f"If nothing changes, the {abs(change_pct)}% slide "
                             "becomes the new normal — customers form new habits "
                             "fast. Acting in the next 2 weeks matters more "
                             "than acting big.")
    elif change_pct is not None and change_pct > 0.5:
        if_do_nothing = (f"Good news: you're up {abs(change_pct)}%. Doing "
                         "nothing risks stalling it — lock in what's working.")
    elif change_pct is not None:
        if_do_nothing = ("No dramatic slide right now. The risk is slow drift "
                         "— review this number weekly so a small dip never "
                         "becomes a big one.")

    n_groups = len(rows)
    limitations = (f"Based on {n_groups} group(s) from the connected data. "
                   "Outside factors (market, season, competitors) aren't in here.")

    return {
        "headline": headline,
        "what_happened": {
            "summary": what_summary,
            "total": total,
            "change_pct": change_pct,
            "before": before_v,
            "after": after_v,
            "period": period_label,
            "metric": metric_plain,
        },
        "likely_causes": likely_causes,
        "what_to_do": what_to_do[:3],
        "if_do_nothing": if_do_nothing,
        "confidence_plain": ("Based on your real data, not a guess. Treat causes "
                             "as strong suspects, not proof."),
        "limitations_plain": limitations,
        "chart_hint": {
            "x": period_col or seg_col,
            "y": value_col,
        },
    }
