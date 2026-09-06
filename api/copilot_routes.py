from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from core.deps import get_current_user
from core.config import get_session

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class CopilotRequest(BaseModel):
    question: str
    context: Optional[dict[str, Any]] = None


@router.post("")
async def copilot_endpoint(body: CopilotRequest, user: dict = Depends(get_current_user)):
    try:
        session = get_session(user["user_id"])
        provider = session.get("provider")
        if not provider:
            raise HTTPException(status_code=400, detail="No LLM provider configured. Connect a source first.")

        context = body.context or {}
        current_query = context.get("currentQuery", "")
        current_result = context.get("currentResult")

        result_text = ""
        if current_result:
            data = current_result.get("data") or current_result.get("table", {}).get("rows", [])
            if data:
                result_text = f"\nCurrent result data ({len(data)} rows): {str(data[:3])[:500]}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA Copilot, a helpful data analysis assistant. "
                    "Answer questions concisely about the user's current query, results, charts, and KPIs. "
                    "Keep answers short (1-3 sentences). Suggest next steps when appropriate."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current query: {current_query}\n"
                    f"{result_text}\n\n"
                    f"Copilot question: {body.question}"
                ),
            },
        ]

        answer = provider.chat("story", messages, num_predict=200)
        return {"ok": True, "answer": answer}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
