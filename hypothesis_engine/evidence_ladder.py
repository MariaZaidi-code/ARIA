"""Measured evidence grades for hypothesis candidates.

These labels describe *observed support*, never model confidence or proof of
causality. Counterevidence must be measured, not a missing-data caveat.
"""

from __future__ import annotations

ORDER = ["Strong evidence", "Moderate evidence", "Limited evidence",
         "Insufficient evidence", "Contradictory evidence"]

_RANK = {label: i for i, label in enumerate(ORDER)}


def normalize(strength: str, n_support: int = 0, n_against: int = 0) -> str:
    """Downgrade evidence when *measured* observations conflict.

    More counterevidence than support -> Contradictory.
    Some counterevidence, but not a majority -> one level weaker.
    A missing causal link or a limitation is not counterevidence.
    """
    grade = (strength or "").strip()
    if grade not in _RANK:
        grade = "Insufficient evidence"
    if grade == "Contradictory evidence":
        return grade
    support = max(0, int(n_support))
    against = max(0, int(n_against))
    if against > support:
        return "Contradictory evidence"
    if against:
        return ORDER[min(_RANK[grade] + 1, 3)]
    return grade


def rank_key(strength: str) -> int:
    return _RANK.get(strength, 3)


def assess_observed_pattern(kind: str, pattern: dict | None) -> dict:
    """Describe evidence and alternatives for a *measured* intelligence card.

    The listing is only a suggested question; grades here are assigned after
    the detail endpoint has retrieved real grouped totals or time buckets.
    """
    p = pattern or {}
    points = p.get("series") or p.get("points") or []
    out = {
        "evidence_grade": "Insufficient evidence",
        "evidence_reason": "This is a question to test; no measured result is available yet.",
        "measured_contradictions": [],
        "settled_data_notes": [],
        "rivals": [],
        "data_needed": "More observations and a comparison across periods or groups.",
    }
    if kind == "segment":
        out["rivals"] = [
            "Group totals may differ because the groups contain different numbers of records.",
            "Average value per record could differ even when totals look similar.",
        ]
        out["data_needed"] = "Compare group sizes and values per record across the same period."
        if len(points) < 2:
            return out
        try:
            vals = [float(x["value"]) for x in points]
        except (KeyError, TypeError, ValueError):
            return out
        if not all(__import__("math").isfinite(v) for v in vals):
            return out
        high, low = max(vals), min(vals)
        if high <= 0:
            return out
        gap = (high - low) / high * 100
        out["settled_data_notes"] = [
            f"Measured totals differ by {gap:.1f}% between the highest and lowest group."
        ]
        if gap < 5:
            out["measured_contradictions"] = [
                f"The measured gap is only {gap:.1f}%; it does not support a meaningful group spread."
            ]
            out["evidence_grade"] = normalize("Limited evidence", 0, 1)
            out["evidence_reason"] = "The measured group totals do not support the proposed large difference."
        else:
            out["evidence_grade"] = "Limited evidence"
            out["evidence_reason"] = (
                "Group totals show a real difference, but this alone cannot explain why it exists."
            )
        return out

    if kind == "trend":
        out["rivals"] = [
            "The shift may reflect a few unusually large or small periods.",
            "Changes in the mix of records may explain the aggregate movement.",
        ]
        out["data_needed"] = "Check more time periods and compare the change within groups."
        if len(points) < 2:
            return out
        try:
            vals = [float(x["value"]) for x in points]
        except (KeyError, TypeError, ValueError):
            return out
        if not all(__import__("math").isfinite(v) for v in vals):
            return out
        cut = max(1, len(vals) // 2)
        early, late = sum(vals[:cut]), sum(vals[cut:])
        if early == 0:
            out["evidence_reason"] = "The earlier period totals zero, so a reliable percentage change is unavailable."
            out["data_needed"] = "A non-zero earlier baseline or comparable raw totals."
            return out
        pct = (late - early) / abs(early) * 100
        out["settled_data_notes"] = [
            f"Earlier-period total: {early:g}; later-period total: {late:g} ({pct:+.1f}%)."
        ]
        if abs(pct) < 5:
            out["evidence_reason"] = "The observed change is small; the direction is not strong enough to infer a trend."
            return out
        grade = "Moderate evidence" if len(vals) >= 6 else "Limited evidence"
        out["evidence_reason"] = (
            "The earlier and later totals differ; this supports a measured change, not its cause."
        )
        # A reversed final bucket is a second, independently measured
        # time-window signal; a small wobble is not treated as opposition.
        prev, last = vals[-2], vals[-1]
        if prev != 0:
            last_pct = (last - prev) / abs(prev) * 100
            if abs(last_pct) >= 5 and (last_pct > 0) != (pct > 0):
                out["measured_contradictions"] = [
                    f"The latest time bucket moved {last_pct:+.1f}%, opposite to the overall {pct:+.1f}% change."
                ]
                grade = normalize(grade, 1, 1)
                out["evidence_reason"] = (
                    "The overall change is measured, but the latest bucket moved the other way."
                )
        out["evidence_grade"] = grade
    return out
