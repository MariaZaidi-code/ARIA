"""ARIA Insight Agent package.

Public API:
    from insight_agent import InsightAgent, sanitize_json

The implementation lives in :mod:`insight_agent.agent`; this package keeps
imports stable for API routes and downstream callers.
"""

from .agent import InsightAgent, sanitize_json
from .chart_catalog import CHART_OPTIONS, compatible_chart_options

__all__ = [
    "InsightAgent",
    "sanitize_json",
    "CHART_OPTIONS",
    "compatible_chart_options",
]
