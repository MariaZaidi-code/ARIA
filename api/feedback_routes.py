"""Feedback + Personalization routes.

Captures user signals (insight ratings, suggestion clicks, chart preferences)
and uses them to improve presentation-layer ranking without affecting
analytical truth. All personalization operates on the decision/experience
layer only.
"""

import json
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, BaseModel

from core.deps import get_current_user

router = APIRouter()

# ── Preference storage path ─────────────────────────────────────────────
_PREFS_DIR = Path(__file__).resolve().parent.parent / "data" / "preferences"

# Bounded telemetry: arbitrary client text keys must not grow the prefs
# store forever (two concurrent posts / repeated UI events add keys).
_MAX_TEXT_KEYS = 200
_MAX_TEXT_KEY_LEN = 160
_MAX_CHART_CONTEXTS = 100


def _prefs_path(user_id: str) -> Path:
    _PREFS_DIR.mkdir(parents=True, exist_ok=True)
    # user id is always a validated int from get_current_user; still keep
    # digits-only in the filename for belt-and-braces path safety.
    try:
        safe_id = int(str(user_id).strip())
    except (TypeError, ValueError):
        safe_id = 0
    return _PREFS_DIR / f"user_{safe_id}_prefs.json"


def _load_prefs(user_id: str) -> dict:
    p = _prefs_path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            import logging as _logging
            _logging.getLogger("uvicorn.error").warning(
                "prefs load failed for user %s (%s) — defaults returned",
                str(user_id)[:3], type(exc).__name__)
    return {
        "chart_preferences": {},
        "suggestion_clicks": {},
        "insight_ratings": [],
        "chart_type_history": {},
        "preferred_palette": None,
        "preferred_density": "auto",
    }


def load_preferences(user_id: str) -> dict:
    """Public accessor for the per-user preferences store.

    The RL routes reuse this store for integrity checks/ranking context
    without reaching into the private loader.
    """
    return _load_prefs(user_id)


def _save_prefs(user_id: str, prefs: dict):
    # Atomic write like the workspace stores: a crash mid-write must not
    # destroy the file (load then silently fell back to defaults).
    p = _prefs_path(user_id)
    tmp = p.with_name(f"{p.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(prefs, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)
    try:
        if os.name != "nt":
            os.chmod(p, 0o600)
    except Exception:
        pass


def _bound_text_keys(mapping: dict, cap: int = _MAX_TEXT_KEYS) -> dict:
    """Keep only the most-clicked keys, truncated, under a cap."""
    if not isinstance(mapping, dict):
        return {}
    bounded = {}
    for k, v in list(mapping.items())[: cap * 2]:
        key = str(k).strip()[:_MAX_TEXT_KEY_LEN] or "unlabeled"
        cur = bounded.get(key, 0)
        try:
            bounded[key] = int(cur) + int(v or 0)
        except (TypeError, ValueError):
            bounded[key] = int(cur) + 1
    if len(bounded) > cap:
        bounded = dict(sorted(bounded.items(), key=lambda kv: int(kv[1]),
                              reverse=True)[:cap])
    return bounded


# ── Models ──────────────────────────────────────────────────────────────

class InsightRating(BaseModel):
    model_config = ConfigDict(extra="allow")
    insight_id: str = ""
    question: str = ""
    rating: str  # "useful" | "not_useful"
    category: str = "analytics"  # analytics | insight | prediction | prescription


class SuggestionClick(BaseModel):
    model_config = ConfigDict(extra="allow")
    suggestion_text: str
    source: str = "dashboard"  # dashboard | analytics | idle


class ChartPreference(BaseModel):
    model_config = ConfigDict(extra="allow")
    chart_type: str
    context: str = ""  # e.g. "bar_chart_default", "time_series"


class GeneralFeedback(BaseModel):
    model_config = ConfigDict(extra="allow")
    message: str = ""
    category: str = "general"


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/api/feedback")
def submit_feedback(req: GeneralFeedback, user: dict = Depends(get_current_user)):
    """General feedback (legacy endpoint)."""
    return {"ok": True, "message": "Thanks for your feedback."}


@router.post("/api/feedback/insight")
def rate_insight(payload: InsightRating, user: dict = Depends(get_current_user)):
    """Rate an insight as useful or not useful. Used for RL reward signal."""
    if payload.rating not in ("useful", "not_useful"):
        raise HTTPException(status_code=400, detail="rating must be 'useful' or 'not_useful'.")
    if payload.category not in ("analytics", "insight", "prediction", "prescription"):
        raise HTTPException(status_code=400, detail="Unsupported feedback category.")
    prefs = _load_prefs(user["user_id"])
    prefs["insight_ratings"].append({
        "question": payload.question,
        "rating": payload.rating,
        "category": payload.category,
        "timestamp": time.time(),
    })
    # Keep last 200 ratings
    prefs["insight_ratings"] = prefs["insight_ratings"][-200:]
    _save_prefs(user["user_id"], prefs)
    return {"ok": True}


@router.post("/api/feedback/suggestion")
def track_suggestion_click(payload: SuggestionClick, user: dict = Depends(get_current_user)):
    """Track when user clicks a suggestion. Used for suggestion ranking."""
    prefs = _load_prefs(user["user_id"])
    text = payload.suggestion_text.strip()[:_MAX_TEXT_KEY_LEN]
    clicks = _bound_text_keys(prefs.get("suggestion_clicks", {}))
    clicks[text] = clicks.get(text, 0) + 1
    prefs["suggestion_clicks"] = _bound_text_keys(clicks)
    _save_prefs(user["user_id"], prefs)
    return {"ok": True}


@router.post("/api/feedback/chart")
def track_chart_preference(payload: ChartPreference, user: dict = Depends(get_current_user)):
    """Track chart type selection. Used for chart recommendation."""
    prefs = _load_prefs(user["user_id"])
    history = prefs.get("chart_type_history", {})
    key = (payload.context or "general").strip()[:_MAX_TEXT_KEY_LEN] or "general"
    if key not in history:
        history[key] = {}
    history[key][payload.chart_type] = history[key].get(payload.chart_type, 0) + 1
    # Bound both the context subset and the total history size.
    if len(history) > _MAX_CHART_CONTEXTS:
        flatten = [(c, t, n) for c, per in history.items() for t, n in (per or {}).items()]
        flatten.sort(key=lambda x: x[2], reverse=True)
        rebuilt: dict = {}
        for c, t, _n in flatten[: _MAX_CHART_CONTEXTS * 5]:
            rebuilt.setdefault(c, {})[t] = _n
        history = rebuilt
    prefs["chart_type_history"] = history
    _save_prefs(user["user_id"], prefs)
    return {"ok": True}


@router.get("/api/preferences")
def get_preferences(user: dict = Depends(get_current_user)):
    """Get user preferences for personalization."""
    return {"ok": True, "preferences": _load_prefs(user["user_id"])}


@router.post("/api/preferences")
def save_preferences(payload: dict, user: dict = Depends(get_current_user)):
    """Save user preferences (palette, density, etc.)."""
    prefs = _load_prefs(user["user_id"])
    if "preferred_palette" in payload:
        prefs["preferred_palette"] = payload["preferred_palette"]
    if "preferred_density" in payload:
        prefs["preferred_density"] = payload["preferred_density"]
    if "preferred_explanation_style" in payload:
        prefs["preferred_explanation_style"] = payload["preferred_explanation_style"]
    _save_prefs(user["user_id"], prefs)
    return {"ok": True}
