"""RL observability + feedback API (additive; no analytics logic here).

Contract for the future RL model: the frontend records
(state, action, outcome, reward) tuples through these routes. Ranking is
delegated to a replaceable policy object (``core.rl.RLPolicy``,
``baseline-v1`` today) that can only re-rank pre-validated candidates —
swapping in a trained bandit/DQN/PPO later means replacing the policy,
while these routes and the telemetry storage stay stable.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ConfigDict, BaseModel, Field

from api.feedback_routes import load_preferences
from core.config import get_session  # noqa: F401  (session scope parity)
from core.deps import get_current_user
from core.rl import IMPACT_UNKNOWN_NOTE, RLPolicy, load_recent_events, record_event

router = APIRouter()

_RANK_MAX_CANDIDATES = 200
_COMMENT_MAX = 500


class FeedbackEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    event: str = Field(min_length=1, max_length=64)
    state: dict = Field(default_factory=dict)
    action: dict = Field(default_factory=dict)
    outcome: dict = Field(default_factory=dict)
    reward: dict = Field(default_factory=dict)


class PopupFeedback(BaseModel):
    model_config = ConfigDict(extra="allow")
    rating: int = Field(ge=1, le=5, description="Popup check-in, 1-5 stars")
    comment: str = ""
    page: str = ""
    context: dict = {}


class RankRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    candidates: list[dict] = []
    state: dict = {}


def _reward_label(rating: int) -> str:
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


@router.post("/api/rl/event")
def post_event(body: FeedbackEvent, request: Request, user: dict = Depends(get_current_user)):
    """Record a structured UI feedback event (chart kept/changed, insight saved/dismissed...)."""
    import json
    try:
        blob = json.dumps(body.model_dump(), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(status_code=422, detail="Feedback must contain finite JSON values.")
    if len(blob.encode("utf-8")) > 7000:
        raise HTTPException(status_code=413, detail="Feedback is too large. Send summaries only.")
    record_event(
        user["user_id"],
        event=body.event[:64],
        state=body.state,
        action=body.action,
        outcome=body.outcome,
        reward=body.reward,
    )
    return {"ok": True, "impact_note": IMPACT_UNKNOWN_NOTE,
            "persistence": "best_effort", "reward_source": "client_feedback"}


@router.get("/api/rl/events")
def get_events(request: Request, user: dict = Depends(get_current_user), limit: int = 100):
    """Observability: recent RL telemetry for this user (debug/admin)."""
    limit = max(1, min(int(limit), 500))
    return {"ok": True, "events": load_recent_events(user["user_id"], limit=limit)}


@router.post("/api/rl/feedback")
def post_popup_feedback(body: PopupFeedback, request: Request, user: dict = Depends(get_current_user)):
    """Record the random RL feedback popup (1-5 stars + optional comment).

    Reward mapping is deliberately linear and bounded:
    ``(rating - 3) / 2`` -> [-1.0, +1.0]. Telemetry only (no user data is
    mutated), so read-only mobile sessions may submit as well.
    """
    rating = int(body.rating)
    reward = round(max(-1.0, min(1.0, (rating - 3) / 2.0)), 2)
    record_event(
        user["user_id"],
        event="popup_feedback",
        state={
            "page": str(body.page or "")[:40],
            "context": body.context if isinstance(body.context, dict) else {},
        },
        action={"type": "feedback_popup", "value": rating},
        outcome={"comment": str(body.comment or "")[:_COMMENT_MAX]},
        reward={"value": reward, "label": _reward_label(rating), "scale": "1-5 stars"},
    )
    return {"ok": True, "reward": reward, "impact_note": IMPACT_UNKNOWN_NOTE}


@router.get("/api/rl/status")
def get_status(request: Request, user: dict = Depends(get_current_user)):
    """Policy + observability summary for the RL layer (model-ready contract).

    ``model`` stays ``None`` until a trained policy exists; ``baseline-v1``
    serves ranking in the meantime, so consumers can integrate today.
    """
    events = load_recent_events(user["user_id"], limit=500)
    reward_summary = {"positive": 0, "neutral": 0, "negative": 0}
    last_ts = 0.0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        try:
            last_ts = max(last_ts, float(ev.get("ts") or 0))
        except (TypeError, ValueError):
            pass
        reward = ev.get("reward")
        value = reward.get("value") if isinstance(reward, dict) else None
        try:
            fval = float(value) if value is not None else None
        except (TypeError, ValueError):
            fval = None
        if fval is None:
            continue
        if fval > 0:
            reward_summary["positive"] += 1
        elif fval < 0:
            reward_summary["negative"] += 1
        else:
            reward_summary["neutral"] += 1
    policy = RLPolicy()
    return {
        "ok": True,
        "policy": {"name": policy.name, "kind": "deterministic-baseline", "replaceable": True},
        "model": None,
        "events_seen": len(events),
        "reward_summary": reward_summary,
        "last_event_ts": last_ts or None,
        "impact_note": IMPACT_UNKNOWN_NOTE,
    }


@router.post("/api/rl/rank")
def post_rank(body: RankRequest, request: Request, user: dict = Depends(get_current_user)):
    """Rank pre-validated candidates through the active RL policy.

    Contract: callers pass only candidates that already passed validity
    checks (the truth layer is never modified). The baseline policy can
    never promote an invalid candidate and falls back to input order on
    any failure; a trained model plugs in behind the same response shape.
    """
    if len(body.candidates) > _RANK_MAX_CANDIDATES:
        raise HTTPException(status_code=400, detail=f"At most {_RANK_MAX_CANDIDATES} candidates per request.")
    prefs = load_preferences(user["user_id"])
    result = RLPolicy().rank(body.state or {}, body.candidates, prefs=prefs)
    return {"ok": True, **result}
