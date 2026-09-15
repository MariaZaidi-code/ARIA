"""Goal-aware decision intelligence for ARIA.

Canonical implementation lives at ``insight_agent.extensions.decision_intelligence``.
This module re-exports it for backward compatibility.
"""

from insight_agent.extensions.decision_intelligence import DecisionIntelligence

__all__ = ["DecisionIntelligence"]
