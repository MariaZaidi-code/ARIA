"""Compatibility shim: canonical implementation lives in insight_agent.advanced.

Preserved so existing imports (`from insight_agent_advanced import ...`,
`from insight_agent_industry import ...`) keep working. Do not add logic here.
"""
from insight_agent import sanitize_json  # noqa: F401
from insight_agent.advanced import AdvancedInsightAgent  # noqa: F401

InsightAgent = AdvancedInsightAgent

__all__ = ["AdvancedInsightAgent", "InsightAgent", "sanitize_json"]
