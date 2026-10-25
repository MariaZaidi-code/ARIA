"""Component: template-driven business-goal suggestions driven purely by the schema."""

import difflib
import json
import re
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from llm_provider import LLMProvider, create_provider
from core.validation import unknown_sql_tables, empty_sql_tables, unknown_sql_columns
from core.config import SCHEMA_DIR, BASE_DIR
from schema_engine.lexical import singularize

try:
    from langgraph.graph import END, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    END = None
    StateGraph = None


class SuggestionsMixin:
    # ---- _schema_summary_text (_schema_summary_text) ----

    def _schema_summary_text(self):
        """Compact schema description used for LLM-based suggestion generation."""
        lines = []
        for table_name, info in self.tables.items():
            columns = ", ".join(info.get("columns", {}).keys()) or "no columns"
            lines.append(f"- {table_name} ({columns})")
        return "\n".join(lines)

    # ---- get_suggestions (get_suggestions) ----

    def get_suggestions(self, limit=8, use_llm=True):
        """Suggest searchable goals. Uses Mistral after analyzing the schema; falls back to template suggestions when the LLM is unavailable."""
        if not self.tables:
            return ["What insights can we derive from the connected data?"]

        template = self._template_suggestions(limit)
        if not use_llm:
            return template

        prompt = f"""
You are a senior data analyst writing questions for a business user. After
analysing the database tables below, suggest {limit} analytical questions a
data analyst would actually ask of this data. Prefer question archetypes such
as rankings ("top N by ..."), trends over time, comparisons between segments,
distributions, share of total, and anomalies or outliers. Avoid trivial
counts and generic 'show everything' questions.

Schema:
{self._schema_summary_text()}

Output a JSON array of strings only. No explanation, no markdown.
Write them the way a non-technical business user would type them - full
natural-English questions. Never mention raw table or column identifiers
(e.g. write "customers" as a word, not customers.customer_id).
"""
        try:
            # Short, bounded LLM call so suggestions never hang the endpoint.
            content = self.llm.chat("suggest", messages=[{"role": "user", "content": prompt}],
                                    temperature=0.5, num_predict=300, timeout=5)
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*", "", content)
            cleaned = self._clean_llm_suggestions(self._salvage_json_list(content))
            if cleaned:
                # Template questions top up a short LLM list.
                return list(dict.fromkeys(cleaned + template))[:limit]
        except Exception as exc:
            logging.warning("Suggestion generation failed: %s. Using template suggestions.", exc)

        return template

    @staticmethod
    def _salvage_json_list(content):
        """Strings from an LLM reply that should be a JSON array.

        Small models often return almost-JSON (trailing commas, single
        quotes, a numbered list). Parse the array when possible, else
        recover the quoted items, else the list lines.
        """
        text = str(content or "")
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            body = text[start:end + 1]
            try:
                data = json.loads(body)
                if isinstance(data, list):
                    return [str(s) for s in data if isinstance(s, (str, int, float))]
            except ValueError:
                body = re.sub(r",\s*([\]}])", r"\1", body)
                try:
                    data = json.loads(body)
                    if isinstance(data, list):
                        return [str(s) for s in data if isinstance(s, (str, int, float))]
                except ValueError:
                    pass
        quoted = re.findall(r'"([^"\n]{8,200})"|\'([^\'\n]{8,200})\'', text)
        items = [a or b for a, b in quoted]
        if items:
            return items
        lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip()
                 for ln in text.splitlines()]
        return [ln for ln in lines if ln.endswith("?") and len(ln) >= 8]

    def _clean_llm_suggestions(self, items):
        """Keep only plain, answerable questions from LLM output: no raw
        identifiers (underscores, dotted names, SQL), no blocked plain-ask
        types (outliers / correlation / forecast / what-if), no duplicates."""
        blocked = re.compile(
            r"\b(outlier\w*|anomal\w*|correlat\w*|forecast\w*|predict\w*|"
            r"what[- ]if|scenario)\b", re.IGNORECASE)
        out, seen = [], set()
        for raw in items or []:
            s = re.sub(r"\s+", " ", str(raw or "")).strip().strip(",")
            if len(s) < 8 or len(s) > 160:
                continue
            if re.search(r"[_`{}\[\]]|\w\.\w|\bselect\b|\bfrom\b\s+\w+\s+\bwhere\b", s,
                         re.IGNORECASE):
                continue
            if blocked.search(s):
                continue
            key = s.lower()
            if key not in seen:
                seen.add(key)
                out.append(s[:1].upper() + s[1:])
        return out

    # ---- _measure_noun (_measure_noun) ----

    def _measure_noun(self, fact_table, col):
        """Natural noun for a measure column when used in analyst questions:
        'orders.total' -> 'order value', 'order_details.unit_price' -> 'unit price'."""
        col_label = self._natural_label(col)
        if col_label and set(col_label.lower().split()) <= self._GENERIC_TOTAL_WORDS:
            # Single-table/file datasets name the table after the upload
            # (never a business concept): use a neutral noun instead of
            # leaking the filename into the question. Multi-table schemas
            # keep the table-derived noun (generic, data-driven).
            try:
                if len(getattr(self, "tables", {}) or {}) <= 1:
                    return "overall total value"
            except Exception:
                pass
            return f"{self._natural_label(fact_table)} value"
        return col_label

    # ---- _template_suggestions (_template_suggestions) ----

    def _template_suggestions(self, limit=8):
        """Deterministic analyst-style questions (ranking / trend / comparison /
        distribution) built from schema structure only. No raw identifiers leak
        into the text, and no trivial 'how many rows' questions are emitted."""
        tables = list(self.tables.keys())
        if not tables:
            return ["Which factors most affect our key business metric?"]

        per_table = []
        for table_name in tables:
            info = self.tables[table_name]
            plural = self._plural_label(table_name)
            singular = self._natural_label(table_name)
            own_measure = self._pick_measure_column(table_name)
            date_col = next(
                (c for c in info["columns"]
                 if self._classify_column(table_name, c) == "date"),
                None,
            )

            fact_refs = []
            for other, other_info in self.tables.items():
                if other == table_name:
                    continue
                for fk in other_info.get("foreign_keys", []):
                    reference = str(fk.get("referenced_table") or "")
                    normalized = lambda value: str(value).replace('"', '').replace('`', '').lower()
                    exact = normalized(reference) == normalized(table_name)
                    candidates = [t for t in tables if normalized(t).split('.')[-1] == normalized(reference)]
                    if exact or (len(candidates) == 1 and candidates[0] == table_name):
                        fact_refs.append(other)
                        break

            ts = []
            if self._is_entity_table(table_name):
                # Dimension nouns ("products") read naturally; bare table nouns
                # ("diag sales" for a file upload) leak filenames into prose.
                # Referenced (real domain) tables keep table nouns; standalone
                # tables use their text dimension.
                # A grouping is a real text dimension: never a date stored
                # as text ('txn_dt') and, when profiling knows it, never
                # near-unique text (names, free text) while a real one exists.
                _stats = info.get("null_stats") or {}

                def _distinct(c):
                    try:
                        return int((_stats.get(c) or {}).get("distinct_count") or 0)
                    except (TypeError, ValueError):
                        return 0
                _dims = [c for c in info["columns"]
                         if c.lower() != "id" and not c.lower().endswith("_id")
                         and self._classify_column(table_name, c) == "text"
                         and not ({"date", "time", "timestamp"}
                                  & set(self._natural_label(c).split()))]
                dim_col = next((c for c in _dims if 0 < _distinct(c) <= 50),
                               _dims[0] if _dims else None)
                if fact_refs or not dim_col:
                    dim_plural, dim_single = plural, singular
                else:
                    dim_plural = self._plural_label(dim_col)
                    dim_single = self._natural_label(dim_col)
                fact = fact_refs[0] if fact_refs else None
                fact_measure = self._pick_measure_column(fact) if fact else None
                fact_date = None
                if fact:
                    fact_date = next(
                        (c for c in self.tables[fact]["columns"]
                         if self._classify_column(fact, c) == "date"),
                        None,
                    )
                if fact_measure:
                    noun = self._measure_noun(fact, fact_measure)
                    ts.append(f"What are the top {dim_plural} by {noun}?")
                    ts.append(f"Which {dim_plural} contribute the most to {noun}?")
                    if fact_date:
                        ts.append(f"How has {noun} changed over time?")
                    ts.append(f"What is the average {noun} per {dim_single}?")
                elif own_measure:
                    # Standalone (file-like) tables use the bare column label
                    # so filenames never leak ("top products by amount",
                    # never "top diag sales by diag sale value").
                    _own_noun = (self._measure_noun(table_name, own_measure)
                                 if fact_refs else self._natural_label(own_measure))
                    ts.append(
                        f"What are the top {dim_plural} by {_own_noun}?"
                    )
                # Referenced (domain) tables keep the dataset noun the tests
                # and relational UX expect ("metrics for customers");
                # standalone tables stay neutral ("metrics in this data").
                if fact_refs:
                    ts.append(f"What are the most important metrics for {plural}?")
                else:
                    ts.append("What are the most important metrics in this data?")
            else:
                if own_measure:
                    noun = self._measure_noun(table_name, own_measure)
                    if date_col:
                        ts.append(f"What is the trend in {noun} over time?")
                        ts.append(f"How is {noun} distributed?")
                    else:
                        ts.append(f"What is the overall {noun}?")
            if ts:
                per_table.append(ts)

        # Backfill from real measures/dimensions; never invent a metric to
        # satisfy a requested count on a dimension-only schema.
        cardinality_budget = 8
        for table_name in tables:
            measure = self._pick_measure_column(table_name)
            if not measure:
                continue
            noun = self._measure_noun(table_name, measure)
            ts = [f"What is the average {noun}?", f"What is the highest {noun}?",
                  f"What is the lowest {noun}?", f"How is {noun} distributed?",
                  f"Are there unusual values in {noun}?"]
            info = self.tables[table_name]
            for col in info.get("columns", {}):
                if col in (info.get("primary_key") or []) or col.lower() == "id" or col.lower().endswith("_id"):
                    continue
                if self._classify_column(table_name, col) != "text":
                    continue
                if cardinality_budget <= 0:
                    break
                cardinality_budget -= 1
                cardinality = self._estimate_column_cardinality(table_name, col)
                if cardinality is not None and not 2 <= cardinality <= 50:
                    continue
                label = self._natural_label(col)
                ts.extend([f"How does {noun} compare by {label}?",
                           f"What share of {noun} comes from each {label}?"])
            per_table.append(ts)

        # Round-robin across tables so the first N suggestions are varied,
        # not the first N tables repeated with the same template.
        suggestions = []
        max_depth = max(len(ts) for ts in per_table) if per_table else 0
        for depth in range(max_depth):
            for ts in per_table:
                if depth < len(ts):
                    suggestions.append(ts[depth])

        seen = set()
        unique = []
        for suggestion in suggestions:
            if suggestion not in seen:
                seen.add(suggestion)
                unique.append(suggestion)
        return unique[:limit]

