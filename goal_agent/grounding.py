"""Component: schema grounding - relevant tables, join path and semantic resolution of subjects, dimensions and metrics (spec section 6)."""

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


class GroundingMixin:
    # ---- _table_keyword_score (_table_keyword_score) ----

    def _table_keyword_score(self, table_name, info, user_goal_tokens):
        # Token-overlap scoring with singular/plural awareness.
        name_tokens = self._normalize_tokens(table_name)
        score = 0
        name_hit = False
        for tok in user_goal_tokens:
            if tok in name_tokens:
                score += 40
                name_hit = True
            elif tok.endswith("s") and tok[:-1] in name_tokens:
                score += 32
                name_hit = True
            elif name_tokens and (tok + "s") in name_tokens:
                score += 32
                name_hit = True
        for column_name in info.get("columns", {}).keys():
            col_tokens = self._normalize_tokens(column_name)
            for tok in user_goal_tokens:
                if tok in col_tokens:
                    score += 10 if name_hit else 14
                elif tok.endswith("s") and tok[:-1] in col_tokens:
                    score += 6
        score += len(info.get("foreign_keys", [])) * 2
        # Penalty for junction/lookup tables that match only via FK columns.
        if name_hit:
            score += 0
        return score

    # ---- _expand_with_neighbors (_expand_with_neighbors) ----

    def _expand_with_neighbors(self, selected, limit=4):
        """Expand the selected tables through FK neighbors, depth-bounded so
        unrelated tables further out in the graph never get pulled in."""
        expanded = set(selected)
        queue = [(t, 0) for t in selected]
        visited = set()
        while queue and len(expanded) < limit * 2:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if depth >= 2:
                continue
            for neighbor in self.relationship_graph.get(current, []):
                if neighbor in self.tables and neighbor not in expanded:
                    expanded.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return list(expanded)

    # ---- _get_relevant_tables (_get_relevant_tables) ----

    def _get_relevant_tables(self, user_goal, max_tables=3):
        goal_tokens = self._normalize_tokens(user_goal)
        if not goal_tokens:
            goal_tokens = {"data", "summary", "report"}

        ranked = []
        for table_name, info in self.tables.items():
            score = self._table_keyword_score(table_name, info, goal_tokens)
            ranked.append((table_name, score))
        ranked.sort(key=lambda x: x[1], reverse=True)
        selected = [name for name, _ in ranked if _ > 0][:max_tables]

        if not selected:
            selected = [list(self.tables.keys())[0]] if self.tables else []

        if len(selected) < max_tables:
            selected = self._expand_with_neighbors(selected, max_tables)

        return selected[:max_tables]

    # ---- _find_join_hops (_find_join_hops) ----

    def _find_join_hops(self, start, target):
        """BFS join path between two tables using the relationship graph."""
        if start == target:
            return [start]
        queue = [[start]]
        visited = {start}
        while queue:
            path = queue.pop(0)
            for neighbor in self.relationship_graph.get(path[-1], []):
                if neighbor not in self.tables:
                    continue
                if neighbor == target:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return None

    # ---- _determine_join_path (_determine_join_path) ----

    def _determine_join_path(self, relevant_tables):
        """
        Return the ordered join path that connects all relevant tables, using
        the schema's relationship graph. Falls back to the table list itself.
        """
        if not relevant_tables:
            return []
        path = [relevant_tables[0]]
        remaining = relevant_tables[1:]
        while remaining:
            connected = None
            best_local = None
            for table in remaining:
                hop = self._find_join_hops(path[-1], table)
                if hop:
                    best_local = hop
                    connected = table
                    break
            if best_local:
                for node in best_local[1:]:
                    if node not in path:
                        path.append(node)
                remaining = [t for t in remaining if t != connected]
            else:
                # No path found; append remaining tables in order as a fallback.
                path.extend([t for t in remaining if t not in path])
                break
        return path

    # ---- _pick_measure_column (_pick_measure_column) ----

    def _pick_measure_column(self, table_name):
        """First numeric, non-key, non-id, non-FK column (best-guess measure)."""
        info = self.tables[table_name]
        pk = set(info.get("primary_key", []) or [])
        fk_cols = {fk.get("column") for fk in info.get("foreign_keys", [])}
        for col in info["columns"]:
            low = col.lower()
            if col in pk or col in fk_cols or low == "id" \
                    or low.endswith("_id") or low.endswith("id"):
                continue
            if self._classify_column(table_name, col) == "numeric":
                return col
        return None

    # ---- _first_date_column (_first_date_column) ----

    def _first_date_column(self, tables):
        for table in tables:
            if table not in self.tables:
                continue
            for col_name, col_info in self.tables[table].get("columns", {}).items():
                dt = (col_info.get("data_type") or "").lower()
                if any(k in dt for k in ("date", "time", "timestamp")) or "date" in col_name.lower():
                    return (table, col_name)
        return None

    # ---- _is_measure_column (_is_measure_column) ----

    def _is_measure_column(self, table, col):
        """True when a column is a numeric, non-key, non-FK measure candidate."""
        info = self.tables.get(table, {})
        pk = set(info.get("primary_key", []) or [])
        fk_cols = {fk.get("column") for fk in info.get("foreign_keys", [])}
        if col in pk or col in fk_cols:
            return False
        dt = str(info.get("columns", {}).get(col, {}).get("data_type", "")).lower()
        if any(k in dt for k in (
                "int", "decimal", "float", "numeric", "double",
                "money", "real", "bigint", "smallint")):
            return True
        return False

    # ---- _pick_label_column (_pick_label_column) ----

    def _pick_label_column(self, table):
        """Best human-readable grouping/display column of a table (the first
        text, non-key column; otherwise any non-key column)."""
        info = self.tables.get(table, {})
        pk = set(info.get("primary_key", []) or [])
        fk_cols = {fk.get("column") for fk in info.get("foreign_keys", [])}
        text_col = None
        for col in info.get("columns", {}):
            low = col.lower()
            if col in pk or col in fk_cols or low.endswith("_id") or low == "id":
                continue
            if self._classify_column(table, col) == "text" and not text_col:
                text_col = col
            if "name" in low or "label" in low or "title" in low:
                return col
        return text_col

    # ---- _is_dimension_like (_is_dimension_like) ----

    def _is_dimension_like(self, table, col):
        """A column is a breakdown dimension (even when numeric) if its name
        suggests a category/time attribute such as model_year or order_status.
        This keeps quantity/price-style numeric columns as measures while still
        grouping by model_year on any schema."""
        if not self._is_measure_column(table, col):
            return True
        low = col.lower()
        return any(k in low for k in self._DIMENSION_LIKE_NUMERIC)

    # ---- _match_dimension_columns (_match_dimension_columns) ----

    def _match_dimension_columns(self, goal_l, table):
        """Columns of `table` that the goal means AND that are legitimate
        breakdown columns (excludes PK / FK / *_id and pure-measure numeric
        columns). Used for dimension grounding and for choosing the fact table
        of an inferred COUNT."""
        info = self.tables.get(table, {})
        fk_cols = {fk.get("column") for fk in info.get("foreign_keys", [])}
        pk = set(info.get("primary_key", []) or [])
        out = []
        for score, col in self._match_columns(goal_l, table):
            low = col.lower()
            if col in fk_cols or col in pk or low == "id" or low.endswith("_id"):
                continue
            if not self._is_dimension_like(table, col):
                continue
            out.append((score, col))
        return out

    # ---- _pick_fact_table (_pick_fact_table) ----

    def _pick_fact_table(self, goal_l, relevant, subject):
        """Best table to COUNT / aggregate when the metric is inferred
        (spec §3 / §10).

        Rules (generic, schema-driven):
          - if the SUBJECT itself carries the requested dimension columns,
            count the subject ("how many customers");
          - else if a CHILD table that references the subject carries the
            requested dimension columns, count there ("top brands by model
            year" -> count products, because model_year lives in products);
          - else fall back to the subject.
        """
        if not subject:
            return relevant[0] if relevant else None
        if self._match_dimension_columns(goal_l, subject):
            return subject
        best_child = None
        for t in relevant:
            if t == subject:
                continue
            info = self.tables.get(t, {})
            child_of_subject = any(
                fk.get("referenced_table") == subject
                for fk in info.get("foreign_keys", [])
            )
            if not child_of_subject:
                continue
            if self._match_dimension_columns(goal_l, t):
                best_child = t
                break
        return best_child or subject

    # ---- _find_price_quantity_expression (_find_price_quantity_expression) ----

    def _find_price_quantity_expression(self, relevant, concept_tokens):
        """Spec §3: when no single measure column matches a sales-like concept,
        look for a fact table with BOTH a quantity and a unit-price column and
        synthesize quantity * unit_price. Generic, schema-driven, no DB names."""
        for table in relevant:
            info = self.tables.get(table, {})
            cols = list(info.get("columns", {}))
            qty = next((c for c in cols if self._schema_token_matches_goal("quantity", c)
                        or "qty" in c.lower()), None)
            price = next((c for c in cols if self._schema_token_matches_goal("price", c)
                          or "price" in c.lower() or "amount" in c.lower()), None)
            if qty and price and qty != price:
                if self._is_measure_column(table, qty) and self._is_measure_column(table, price):
                    return {
                        "table": table,
                        "expression": f"{table}.{qty} * {table}.{price}",
                        "quantity": qty,
                        "price": price,
                    }
        return None

    # ---- _resolve_semantics (_resolve_semantics) ----

    def _resolve_semantics(self, goal, ir, join_path):
        """Bind the Goal IR concepts to real schema columns/tables (spec §3).

        Two-layer and database-agnostic:
          1. Generic intent lives in the IR (no schema names).
          2. Schema grounding happens HERE: subjects, dimensions and metrics are
             resolved with synonym-aware matching (customers <-> clients,
             model year <-> model_year, ...) plus an explicit confidence and a
             human reason for every binding (spec §6). Never fabricates a
             mapping; unresolved concepts stay None and confidence drops.
        """
        relevant = [t for t in join_path if t in self.tables]
        if not relevant:
            relevant = [list(self.tables.keys())[0]] if self.tables else []
        goal_l = str(goal).lower()

        measures = []
        for table in relevant:
            for col_name in self.tables[table].get("columns", {}):
                if self._is_measure_column(table, col_name):
                    measures.append({"table": table, "column": col_name})
        ir["measures"] = measures

        concept_tokens = {
            "aggregate total": {"total", "sum", "amount", "value", "revenue",
                                "sales", "price", "quantity", "qty", "profit",
                                "units", "cost", "volume"},
            "row count": set(),
            "average value": {"average", "avg", "mean", "value", "price", "amount", "total"},
            "maximum value": {"maximum", "max", "value", "price", "amount"},
            "minimum value": {"minimum", "min", "value", "price", "amount"},
            "profit kpi": {"profit", "margin", "net", "income"},
            "revenue kpi": {"revenue", "amount", "total", "sales", "price"},
            "sales kpi": {"sales", "revenue", "amount", "total", "quantity", "qty", "price"},
        }

        # -- 1) SUBJECT grounding (synonym-aware table matching) -------------
        matched_tables = self._match_tables(goal_l)
        subject = matched_tables[0][1] if matched_tables else None

        # -- 2) DIMENSION grounding -----------------------------------------
        dims = []
        for _score, table in matched_tables:
            label_col = self._pick_label_column(table)
            dims.append({
                "concept": table,
                "resolved_table": table,
                "resolved_column": label_col,
                "confidence": 0.9,
                "reason": "subject table named (or meant) in the question",
            })
        for table in relevant:
            for _score, col in self._match_dimension_columns(goal_l, table):
                dims.append({
                    "concept": col,
                    "resolved_table": table,
                    "resolved_column": col,
                    "confidence": 0.85,
                    "reason": "dimension/breakdown column meant in the question",
                })
        seen_dims = set()
        for d in dims:
            key = (d["resolved_table"], d["resolved_column"])
            if key in seen_dims:
                continue
            seen_dims.add(key)
            ir["dimensions"].append(d)

        # -- 3) METRIC resolution -------------------------------------------
        for metric in ir["metrics"]:
            concept = metric["concept"].lower()
            if metric.get("aggregation") == "COUNT" or concept == "row count":
                fact = self._pick_fact_table(goal_l, relevant, subject)
                metric["resolved_table"] = fact
                metric["resolved_column"] = None
                metric["resolved_expression"] = "COUNT(*)"
                if metric.get("inferred"):
                    metric["confidence"] = 0.6
                    metric["reason"] = (
                        "no explicit measure; count of related records "
                        f"in {fact or 'the fact table'}"
                    )
                else:
                    metric["confidence"] = 0.9
                continue
            tokens = concept_tokens.get(concept, {concept})
            best, best_score = None, 0
            for m in measures:
                s = 0
                for tok in tokens:
                    if tok in self._normalize_tokens(m["column"]):
                        s += 2
                    elif tok.endswith("s") and tok[:-1] in self._normalize_tokens(m["column"]):
                        s += 1
                if s > best_score:
                    best, best_score = m, s
            if best:
                metric["resolved_table"] = best["table"]
                metric["resolved_column"] = best["column"]
                metric["resolved_expression"] = f"{best['table']}.{best['column']}"
                metric["confidence"] = 0.9
                metric["reason"] = "measure column matched the requested metric"
            else:
                # Spec §3: sales-like concept with no single column -> try a
                # computed quantity * unit_price expression from the schema.
                computed = self._find_price_quantity_expression(relevant, tokens)
                if computed:
                    metric["resolved_table"] = computed["table"]
                    metric["resolved_column"] = None
                    metric["resolved_expression"] = computed["expression"]
                    metric["computed_measure"] = True
                    metric["confidence"] = 0.8
                    metric["reason"] = (
                        f"no single measure column; computed "
                        f"{computed['expression']} from the schema"
                    )

        if ir.get("time"):
            date_col = self._first_date_column(relevant)
            if date_col:
                ir["time"]["column"] = f"{date_col[0]}.{date_col[1]}"
                for f in ir["filters"]:
                    if f["column"] is None:
                        f["column"] = f"{date_col[0]}.{date_col[1]}"

        resolved_any = any(m.get("resolved_table") for m in ir["metrics"]) or bool(ir["dimensions"])
        ir["confidence"] = 0.85 if resolved_any else 0.5
        ir["reasoning"] = {
            "intent_confidence": 0.9 if ir.get("operation") else 0.5,
            "schema_confidence": ir["confidence"],
            "relationship_confidence": 0.7,
        }
        required = set()
        for m in ir["metrics"]:
            if m.get("resolved_table"):
                required.add(m["resolved_table"])
        for d in ir["dimensions"]:
            if d.get("resolved_table"):
                required.add(d["resolved_table"])
        ir["required_tables"] = (sorted(required) if required else list(join_path))
        return ir

