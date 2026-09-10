"""Conversation memory for Copilot follow-ups.

Stores a bounded, per-user transcript of (question, resolved context, answer)
turns and provides deterministic coreference resolution so short follow-ups
("what about last year?", "break that down by region", "show me top 5 instead")
reuse the previous entity/measure/grouping without an LLM round-trip.

Provider-independent: no LLM is involved here.
"""

from __future__ import annotations

import re
import threading
import time

_MAX_TURNS = 12
_TTL_SECONDS = 6 * 60 * 60


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


class ConversationMemory:
    """Per-user bounded conversation memory (process-local, TTL'd)."""

    _lock = threading.RLock()
    _store: dict[str, list[dict]] = {}
    _touched: dict[str, float] = {}

    def __init__(self, user_id):
        self.user_id = str(user_id)

    # -- storage ---------------------------------------------------------

    def turns(self) -> list[dict]:
        with self._lock:
            self._evict()
            return list(self._store.get(self.user_id, []))

    def last(self) -> dict | None:
        turns = self.turns()
        return turns[-1] if turns else None

    def append(self, *, question: str, context: dict | None = None,
               answer: str = "", sql: str | None = None) -> None:
        with self._lock:
            self._evict()
            bucket = self._store.setdefault(self.user_id, [])
            bucket.append({
                "question": question,
                "context": context or {},
                "answer": answer,
                "sql": sql,
                "ts": time.time(),
            })
            del bucket[:-_MAX_TURNS]
            self._touched[self.user_id] = time.time()

    def clear(self) -> None:
        with self._lock:
            self._store.pop(self.user_id, None)
            self._touched.pop(self.user_id, None)

    def _evict(self) -> None:
        now = time.time()
        stale = [u for u, t in self._touched.items() if now - t > _TTL_SECONDS]
        for u in stale:
            self._store.pop(u, None)
            self._touched.pop(u, None)

    # -- coreference -----------------------------------------------------

    # Strong reference phrases that only make sense with prior context.
    _FOLLOWUP_MARKERS = (
        "what about", "how about", "and last", "and the same", "the same",
        "break that", "break it down", "those", "that one", "why", "instead",
        "drill down", "go deeper", "expand on", "for those", "for that",
    )

    @classmethod
    def is_followup(cls, question: str) -> bool:
        """Heuristic: short, reference-heavy questions that need prior context.

        Deliberately conservative — a fully self-contained question (even a
        long one that contains a marker word like 'that') must NOT be rewritten
        with stale context.
        """
        q = _norm(question)
        if not q:
            return False
        if len(q.split()) <= 4:
            return True
        words = set(re.findall(r"[a-z0-9]+", q))
        for marker in cls._FOLLOWUP_MARKERS:
            if " " in marker:
                if marker in q:
                    return True
            elif marker in words:
                return True
        return False

    def resolve(self, question: str) -> str:
        """Return `question` enriched with prior-turn references when needed.

        Deterministic and conservative: only prepends context that actually
        exists, and never invents entities. A standalone question is returned
        unchanged.
        """
        if not self.is_followup(question):
            return question
        prev = self.last()
        if not prev:
            return question
        ctx = prev.get("context") or {}
        bits = []
        prev_q = prev.get("question")
        if prev_q:
            bits.append(f"Previous question: {prev_q}")
        for key, label in (("entity", "entity"), ("measure", "measure"),
                           ("group_by", "grouping"), ("tables", "tables")):
            val = ctx.get(key)
            if isinstance(val, (list, tuple)) and val:
                bits.append(f"Previous {label}: {', '.join(str(v) for v in val[:4])}")
            elif isinstance(val, str) and val:
                bits.append(f"Previous {label}: {val}")
        if not bits:
            return question
        return "\n".join(bits) + f"\nCurrent question: {question}"