"""Compatibility shim: canonical implementation lives in insight_agent.industry.

Preserved so existing imports (`from insight_agent_industry import ...`) keep
working. Do not add logic here.
"""
from insight_agent import sanitize_json  # noqa: F401
from insight_agent.industry import IndustryInsightAgent  # noqa: F401

InsightAgent = IndustryInsightAgent

__all__ = ["IndustryInsightAgent", "InsightAgent", "sanitize_json"]
