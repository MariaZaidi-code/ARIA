"""Feedback endpoint — minimal so frontend submitFeedback works."""
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from core.deps import get_current_user

router = APIRouter()

class FeedbackPayload(BaseModel):
    message: str = ""
    category: str = "general"

@router.post("/api/feedback")
def submit_feedback(req: Request, payload: FeedbackPayload, user: dict = Depends(get_current_user)):
    return {"ok": True, "message": "Thanks for your feedback."}
