"""Prescription Engine: evidence-gated action recommendations.

Pipeline: evidence -> problem -> driver -> controllability -> candidates ->
scenarios -> rank. Numbers always come from deterministic statistics;
an LLM may only rephrase wording at the routes layer.
"""
from .engine import analyze, run_scenario, classify_driver, improvement_up, analyze_document

__all__ = ["analyze", "run_scenario", "classify_driver", "improvement_up", "analyze_document"]
