"""Component: SQL generation, repair and semantic validation (read-only, extremes, missing joins, unknown columns, fan-out)."""

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

logger = logging.getLogger(__name__)

class SqlMixin:
    # ---- _is_read_only_sql (_is_read_only_sql) ----

    def _is_read_only_sql(self, sql):
        """True only for read-only SQL (SELECT / CTE-WITH). Deterministically
        rejects INSERT/UPDATE/DELETE/DDL/DCL/DML before the DB round-trip.
        Returns False for empty/None SQL (not a valid statement).
        Delegates to the single shared guard in core.validation."""
        from core.validation import is_read_only_sql as _shared_is_read_only
        return _shared_is_read_only(sql)

    # ---- _warnings_for_sql (_warnings_for_sql) ----

    def _warnings_for_sql(self, sql):
        """Warn when the final query joins through an UNCERTAIN/REVIEW
        relationship (spec §5: do not silently use uncertain relationships) or
        through a low-confidence inferred relationship (spec §6)."""
        warnings = []
        if not sql:
            return warnings
        ref_tables = {t.lower() for t in self._sql_structure(sql)["in_from"]}
        if not ref_tables:
            return warnings
        for key in sorted(self.uncertain_edge_keys):
            src_table = key.split("->")[0].split(".")[0].lower()
            tgt_table = key.split("->")[1].split(".")[0].lower()
            if src_table in ref_tables and tgt_table in ref_tables:
                warnings.append(
                    f"Relationship {key} is UNCERTAIN/REVIEW in the Schema Agent "
                    "output. It was used in this query - validate the join manually."
                )
        low_trust = {"MEDIUM_CONFIDENCE_INFERRED", "LOW_CONFIDENCE_INFERRED"}
        for edge in getattr(self, "relationship_edges", []):
            if edge.get("trust") not in low_trust:
                continue
            if (edge["left_table"].lower() in ref_tables
                    and edge["right_table"].lower() in ref_tables):
                warnings.append(
                    f"Relationship {edge['left_table']}.{edge['left_column']} -> "
                    f"{edge['right_table']}.{edge['right_column']} is "
                    f"{edge['trust']} in the Schema Agent output. It was used in "
                    "this query - validate the join manually."
                )
        return warnings

    # ---- _clean_sql (_clean_sql) ----

    def _clean_sql(self, raw_sql):
        if not raw_sql or not str(raw_sql).strip():
            return "SELECT 1;"
        cleaned = str(raw_sql).strip()
        cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        # Only strip double-quotes that wrap the ENTIRE statement (the LLM
        # sometimes wraps its answer in quotes).  Never strip quotes around
        # individual identifiers — they protect reserved words and
        # case-sensitive names (e.g. SELECT "order" FROM "order").
        if cleaned.startswith('"') and cleaned.endswith('"') and cleaned.count('"') == 2:
            cleaned = cleaned[1:-1]
        # Small local models often ECHO the prompt's instruction sentences into
        # the answer ("with null values last. The final SQL statement is
        # provided without explanations or markdown; ..."). A real statement is
        # SELECT, or a genuine CTE (WITH <name> AS ( ... )). Plain English
        # "with ..." must NOT be mistaken for a WITH clause (it silently
        # corrupts the SQL), and the statement start must be the FIRST
        # top-level keyword: taking the last SELECT would capture inner
        # SELECTs from subqueries/CTEs and corrupt the query.
        stmt_pattern = re.compile(
            r"\bWITH\s+[A-Za-z_]\w*\s+AS\s*\(|\bSELECT\b|"
            r"\bINSERT\s+INTO\b|\bUPDATE\b|\bDELETE\s+FROM\b",
            re.IGNORECASE,
        )
        tail_pattern = re.compile(
            r"(?i)\b(the final sql statement|without explanations|no explanations|"
            r"here(?:'s| is) (?:the|your) final|output only[^\n]*|markdown|"
            r"with null values (?:last|first)[^\n]*|"
            r"this (?:query|sql) (?:is|uses|returns)[^\n]*)"
        )
        statements = []
        for fragment in cleaned.split(";"):
            match = stmt_pattern.search(fragment)
            if not match:
                continue
            frag = fragment[match.start():].strip()
            cut = tail_pattern.search(frag)
            if cut:
                frag = frag[:cut.start()].strip()
            if frag:
                statements.append(frag)
        if statements:
            return statements[-1].rstrip(";") + ";"
        # No real statement found: return the raw text so the validation layer /
        # repair loop sees it as broken and asks the model to fix it.
        return str(raw_sql).strip() + ";"

    # ---- _find_nested_aggregates (_find_nested_aggregates) ----

    def _find_nested_aggregates(self, sql):
        """Return the nested-aggregate snippets found in sql, e.g. AVG(SUM(...)).

        Matches an aggregate keyword directly wrapping another aggregate keyword.
        """
        matches = re.findall(
            r"\b(AVG|SUM|COUNT|MIN|MAX)\s*\(\s*(?:DISTINCT\s+)?(AVG|SUM|COUNT|MIN|MAX)\s*\(",
            sql,
            re.IGNORECASE,
        )
        return [f"{a}({b}" for a, b in matches]

    # ---- _quote (_quote) ----

    @staticmethod
    def _quote(name, dialect=None):
        """Quote an identifier (same pattern as api/schema_intel._safe_name).

        Escapes embedded double quotes; backticks for MySQL. Used for
        identifiers only — never for values (values always go via text()
        bound parameters).
        """
        safe = str(name or "")
        if (dialect or "") == "mysql":
            return f"`{safe.replace('`', '``')}`"
        return f'"{safe.replace(chr(34), chr(34) + chr(34))}"'

    def _quoted(self, name):
        return self._quote(name, getattr(self, "dialect", "postgresql"))

    # ---- _columns_by_type (_columns_by_type) ----

    def _columns_by_type(self):
        """Return {table: {column: data_type}} for datatype validation."""
        out = {}
        for t, info in (self.tables or {}).items():
            cols = info.get("columns", {}) or {}
            if isinstance(cols, dict):
                out[t] = {c: (v.get("data_type", "") if isinstance(v, dict) else "")
                          for c, v in cols.items()}
            else:
                out[t] = {str(c): "" for c in cols}
        return out

    # ---- _find_incompatible_aggregations (_find_incompatible_aggregations) ----

    def _find_incompatible_aggregations(self, sql):
        """SUM/AVG over text/datetime columns. Delegates to core.validation."""
        from core.validation import find_incompatible_aggregations as _inc
        return _inc(sql, self._columns_by_type())

    # ---- _validate_generated_sql (_validate_generated_sql) ----

    def _validate_generated_sql(self, sql):
        """Post-generation gate (n.txt item 2): one call covering nonexistent
        table/column, nested aggregates and incompatible datatypes. Returns a
        list of issue strings ([] = PASS). JOIN-shape checks
        (_find_missing_from_tables / pk-fk) run alongside in the retry loop."""
        from core.validation import validate_generated_sql as _validate
        columns_by_table = {n: list(i.get("columns", {})) for n, i in self.tables.items()}
        return _validate(
            sql,
            schema_tables=list(self.tables),
            columns_by_table=columns_by_table,
            columns_by_type=self._columns_by_type(),
        )

    def _enforce_execution_guards(self, sql):
        """Fail-closed allowlist gate before EVERY execution.

        Asserts ``is_read_only_sql()`` AND ``validate_generated_sql()``
        unknown tables/columns == []. Raises RuntimeError on failure; never
        coerces to a forgiving default.
        """
        from core.validation import enforce_readonly_guards as _enforce
        mapping = {
            name: list(info.get("columns", {}) or {})
            for name, info in (getattr(self, "tables", {}) or {}).items()
        }
        return _enforce(sql, mapping)

    # ---- _goal_asks_for_aggregation (_goal_asks_for_aggregation) ----

    def _goal_asks_for_aggregation(self, user_goal):
        """True if the goal text clearly wants an aggregation / breakdown, in
        which case a bare `SELECT *` answer is almost certainly wrong."""
        goal = (user_goal or "").lower()
        markers = (
            "total", "count", "how many", "number of", "sum of", "average", "avg",
            "mean", "per ", "by ", "maximum", "minimum", "highest", "lowest",
            "top ", "share", "percentage", "breakdown", "distribution",
        )
        return any(m in goal for m in markers)

    # ---- _is_extremes_goal (_is_extremes_goal) ----

    def _is_extremes_goal(self, user_goal):
        """True if the goal explicitly asks for BOTH the top and bottom of a
        ranking (e.g. 'highest and lowest', 'most and least', 'max and min',
        'best and worst', 'top and bottom')."""
        goal = re.sub(r"[^a-z\s]", " ", (user_goal or "").lower())
        words = set(goal.split())
        has_max = bool(words & self._EXTREMES_MAX)
        has_min = bool(words & self._EXTREMES_MIN)
        return has_max and has_min

    # ---- _fix_extremes_sql (_fix_extremes_sql) ----

    def _fix_extremes_sql(self, user_goal, sql):
        """If the goal asks for both extremes and `sql` is a single-sided
        `ORDER BY ... (ASC|DESC) ... LIMIT 1`, strip the trailing LIMIT so the
        full ranking comes back. Returns (sql, changed)."""
        if not sql or not self._is_extremes_goal(user_goal):
            return sql, False
        if not re.search(r"\bORDER\s+BY\b[\s\S]*\b(ASC|DESC)\b", sql, re.IGNORECASE):
            return sql, False
        new_sql, n = re.subn(
            r"\s+LIMIT\s+\d+(?:\s+OFFSET\s+\d+)?(\s*;?\s*)$",
            r"\1",
            sql.strip(),
            count=1,
            flags=re.IGNORECASE,
        )
        if n:
            logger.warning(
                "Extremes goal detected; stripped trailing LIMIT so both the "
                "highest and lowest appear in the result set."
            )
            return new_sql.strip(), True
        return sql, False

    # ---- _sql_structure (_sql_structure) ----

    def _sql_structure(self, sql):
        """Return a dict describing the FROM/JOIN structure of `sql`:

          - in_from:    set of table names present in FROM/JOIN clauses
          - alias_to_name, name_to_alias: alias mappings
          - first_ref:  reference token (alias or bare name) of the FIRST
                        FROM table — the only table guaranteed visible at the
                        point right after the FROM clause.
          - intro:      table name -> byte position just after the clause that
                        introduces it (end of the FROM/JOIN block).

        Implemented as a positional scan that skips parenthesized subqueries
        so a JOIN/ON keyword inside a subquery is never mistaken for a
        top-level clause.
        """
        out = {
            "in_from": set(),
            "alias_to_name": {},
            "name_to_alias": {},
            "first_ref": None,
            "intro": {},
        }
        pos = 0
        first = True
        depth = 0
        while pos < len(sql):
            ch = sql[pos]
            if ch == "(":
                depth += 1
                pos += 1
                continue
            if ch == ")":
                depth = max(0, depth - 1)
                pos += 1
                continue
            if depth > 0:
                pos += 1
                continue
            # Quoted identifiers (e.g. FROM "walmart") must resolve: the old
            # trailing \b never matches after a closing quote (quote and space
            # are both non-word chars), so quoted tables were invisible here.
            # The lookahead accepts a closing quote or any non-identifier char.
            m = re.search(
                r"\b(?:FROM|JOIN)\s+[\"'`\[]?([A-Za-z_][A-Za-z0-9_]*)(?:[\"'`\]])?(?![A-Za-z0-9_])",
                sql[pos:], re.IGNORECASE,
            )
            if not m:
                break
            table = m.group(1)
            out["in_from"].add(table)
            after = pos + m.end()
            alias = None
            tail = sql[after:]
            am = re.match(r"\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)\b", tail, re.IGNORECASE)
            if am:
                alias = am.group(1)
            else:
                am = re.match(r"\s+([A-Za-z_][A-Za-z0-9_]*)\b", tail, re.IGNORECASE)
                if am and am.group(1).lower() not in self._SQL_KEYWORDS:
                    alias = am.group(1)
            if alias and alias.lower() not in self._SQL_KEYWORDS:
                out["alias_to_name"][alias] = table
                out["name_to_alias"][table] = alias
                after += am.end()
            if first:
                out["first_ref"] = out["name_to_alias"].get(table, table)
                first = False
            out["intro"][table] = self._clause_end(sql, after)
            pos = after
        return out

    # ---- _clause_end (_clause_end) ----

    def _clause_end(self, sql, start):
        """Byte position where the clause starting at `start` ends: the next
        top-level JOIN/WHERE/GROUP/ORDER/HAVING/LIMIT/OFFSET keyword or `;`."""
        depth = 0
        i = start
        n = len(sql)
        while i < n:
            ch = sql[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == ";":
                return i
            elif depth == 0:
                m = re.match(
                    r"\b(?:JOIN|WHERE|GROUP|ORDER|HAVING|LIMIT|OFFSET)\b",
                    sql[i:], re.IGNORECASE,
                )
                if m:
                    return i
            i += 1
        return n

    # ---- _missing_refs (_missing_refs) ----

    def _missing_refs(self, sql):
        """Return a list of {'table', 'ref'} for tables referenced via a
        qualified column but missing from FROM/JOIN. `ref` is the token the
        query actually uses for that table (an alias like `b`, or the bare
        table name). Unknown prefixes are resolved to the single schema table
        whose name starts with that prefix (the model invented an alias without
        declaring `FROM <table> <alias>`)."""
        if not sql:
            return []
        struct = self._sql_structure(sql)
        in_from_lc = {t.lower() for t in struct["in_from"]}
        if not in_from_lc:
            return []
        table_names_lc = {t.lower() for t in self.tables}
        found = {}
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*|\*)\b", sql):
            prefix = m.group(1).lower()
            if prefix in struct["alias_to_name"]:
                table = struct["alias_to_name"][prefix].lower()
            elif prefix in table_names_lc:
                table = prefix
            else:
                candidates = [t for t in self.tables if t.lower().startswith(prefix)]
                if len(candidates) != 1:
                    continue
                table = candidates[0].lower()
            if table not in in_from_lc and table in table_names_lc:
                found[table] = prefix
        return [{"table": t, "ref": r} for t, r in sorted(found.items())]

    # ---- _find_missing_from_tables (_find_missing_from_tables) ----

    def _find_missing_from_tables(self, sql):
        """Return table names that are referenced (via `tbl.col` or a JOIN ON
        condition) but never appear in a FROM/JOIN clause."""
        return [m["table"] for m in self._missing_refs(sql)]

    # ---- _inject_missing_joins (_inject_missing_joins) ----

    def _inject_missing_joins(self, sql, missing):
        """Deterministically inject JOINs for tables that are referenced but
        missing from FROM/JOIN. Only inject when there is a clear FK edge to the
        FIRST table in FROM â€” the one guaranteed to be visible at the insertion
        point (a table referenced in an earlier ON clause must be introduced
        before that clause). Returns (new_sql, injected_count) or (sql, 0)."""
        if not missing:
            return sql, 0
        struct = self._sql_structure(sql)
        first_ref = struct["first_ref"]
        intro_pos = struct["intro"]
        if first_ref is None or not intro_pos:
            return sql, 0
        first_table = struct["alias_to_name"].get(first_ref, first_ref)
        if first_table not in intro_pos:
            return sql, 0
        edges = self._fk_edges()
        joins = []
        for item in self._missing_refs(sql):
            table = item["table"]
            ref = item["ref"]
            real = next((t for t in self.tables if t.lower() == table), table)
            alias_txt = "" if ref == table else f" {ref}"
            candidate = None
            for (src, col, ref_t, ref_col) in edges:
                if src.lower() == table and ref_t.lower() == first_table.lower():
                    candidate = f"JOIN {real}{alias_txt} ON {ref}.{col} = {first_ref}.{ref_col}"
                    break
            if candidate is None:
                for (src, col, ref_t, ref_col) in edges:
                    if ref_t.lower() == table and src.lower() == first_table.lower():
                        candidate = f"JOIN {real}{alias_txt} ON {first_ref}.{col} = {ref}.{ref_col}"
                        break
            if candidate:
                joins.append(candidate)
        if not joins:
            return sql, 0
        inject_at = intro_pos[first_table]
        injection = " " + " ".join(joins)
        new_sql = sql[:inject_at] + injection + " " + sql[inject_at:]
        return new_sql, len(joins)

    # ---- _join_clauses (_join_clauses) ----

    def _join_clauses(self, sql):
        """Return (start, end, table, on_start, on_end) for every JOIN clause,
        where on_start/on_end span the ON condition (None if no ON clause)."""
        clauses = []
        pos = 0
        while True:
            m = re.search(
                r"\bJOIN\s+([\"'`]?)([A-Za-z_][A-Za-z0-9_]*)\1\b",
                sql[pos:], re.IGNORECASE,
            )
            if not m:
                break
            start = pos + m.start()
            table = m.group(2)
            after = pos + m.end()
            tail = sql[after:]
            am = re.match(r"\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)\b", tail, re.IGNORECASE)
            if not am:
                am = re.match(r"\s+([A-Za-z_][A-Za-z0-9_]*)\b", tail, re.IGNORECASE)
                if am and am.group(1).lower() in self._SQL_KEYWORDS:
                    am = None
            if am:
                after += am.end()
            om = re.search(r"\bON\b", sql[after:], re.IGNORECASE)
            if not om:
                end = self._clause_end(sql, after)
                clauses.append((start, end, table, None, None))
            else:
                cond_start = after + om.end()
                cond_end = self._clause_end(sql, cond_start)
                clauses.append((start, cond_end, table, cond_start, cond_end))
            pos = cond_end if om else end
        return clauses

    # ---- _repair_unknown_columns (_repair_unknown_columns) ----

    def _repair_unknown_columns(self, sql, columns_by_table, bad_columns):
        """Deterministically fix hallucinated column references WITHOUT an LLM.

        Handles two failure modes the LLM repair loop repeatedly fails on:
          1. `tbl.col` where `col` actually lives on another table in the query's
             schema -> rewrite the qualifier to the owning table (the missing-FROM
             guard then injects the required FK join).
          2. a JOIN whose ON condition uses an unresolvable column -> drop that
             hallucinated JOIN entirely (only when the joined table is not used
             anywhere else in the query).

        JOIN ON predicates whose rewrite would self-compare the same table
        (``rooms.room_id = rooms.room_id``) are refused and instead dropped or
        left for the LLM. Returns (repaired_sql, changed).
        """
        if not bad_columns or not sql:
            return sql, False
        bad_set = {b.lower() for b in bad_columns}
        table_cols_lc = {t: {c.lower() for c in cols} for t, cols in columns_by_table.items()}
        col_owners = {}
        for t, cols in table_cols_lc.items():
            for c in cols:
                col_owners.setdefault(c, []).append(t)
        struct = self._sql_structure(sql)
        in_from_lc = {t.lower() for t in struct["in_from"]}

        def resolve_prefix(prefix):
            p = prefix.lower()
            if p in struct["alias_to_name"]:
                return struct["alias_to_name"][p].lower()
            if p in table_cols_lc:
                return p
            cands = [t for t in table_cols_lc if t.startswith(p)]
            return cands[0].lower() if len(cands) == 1 else None

        def near_match(table, col):
            norm = re.sub(r"[^a-z0-9]", "", col.lower())
            for c in table_cols_lc.get(table, ()):
                if re.sub(r"[^a-z0-9]", "", c) == norm:
                    return c
            for c in table_cols_lc.get(table, ()):
                if len(c) >= 4 and (norm.rstrip("s") == c.rstrip("s") or norm == c[:-1]):
                    return c
            return None

        on_regions = [(s, e) for (_, _, _, s, e) in self._join_clauses(sql) if s is not None]

        def other_side_table(pos, on_start, on_end):
            """Resolve the table of the operand on the other side of the `=`
            nearest to `pos` within an ON condition."""
            seg = sql[on_start:on_end]
            local = pos - on_start
            eq = seg.rfind("=", 0, local)
            eq2 = seg.find("=", local)
            bounds = []
            if eq != -1:
                bounds.append((seg.rfind("=", 0, eq - 1), eq))
            if eq2 != -1:
                bounds.append((eq, seg.find("=", eq2 + 1)))
            region = None
            for lo, hi in bounds:
                if lo <= local <= hi:
                    region = seg[lo + 1:hi if hi != -1 else len(seg)]
                    break
            if not region:
                return None
            m = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*[A-Za-z_][A-Za-z0-9_]*\b", region)
            return resolve_prefix(m.group(1)) if m else None

        def in_on(pos):
            return next(((s, e) for s, e in on_regions if s <= pos < e), None)

        # --- pass 1: rewrite qualifiers to the column's real owner -------------
        replacements = []
        for m in re.finditer(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*|\*)\b", sql
        ):
            prefix, col = m.group(1), m.group(2)
            if col == "*":
                continue
            tbl = resolve_prefix(prefix)
            if tbl is None or f"{tbl}.{col}".lower() not in bad_set:
                continue
            real = near_match(tbl, col)
            if real:
                replacements.append((m.start(), m.end(), f"{prefix}.{real}"))
                continue
            owners = [t for t in col_owners.get(col.lower(), []) if t != tbl and t not in in_from_lc]
            if len(owners) != 1:
                continue
            region = in_on(m.start())
            if region:
                other = other_side_table(m.start(), region[0], region[1])
                if other == owners[0]:
                    continue  # would become X.x = X.x (self-comparison); drop/LLM instead
            replacements.append((m.start(), m.end(), f"{owners[0]}.{col}"))
        if replacements:
            out = sql
            for start, end, repl in sorted(replacements, reverse=True):
                out = out[:start] + repl + out[end:]
            if not unknown_sql_columns(out, columns_by_table):
                return out, True

        # --- pass 2: drop hallucinated JOINs (unresolvable ON column) ----------
        for (start, end, table, on_start, on_end) in self._join_clauses(sql):
            if on_start is None:
                continue
            cond = sql[on_start:on_end]
            used_elsewhere = False
            alias = struct["alias_to_name"].get(table)
            for token in {table, alias} - {None}:
                remaining = sql[:start] + sql[end:]
                if re.search(rf"\b{re.escape(token)}\s*\.\s*[A-Za-z_][A-Za-z0-9_]*\b",
                             remaining, re.IGNORECASE):
                    used_elsewhere = True
                    break
            if used_elsewhere:
                continue
            cond_bad = [b for b in bad_set if re.search(
                rf"\b{re.escape(b.split('.')[0])}\s*\.\s*{re.escape(b.split('.')[1])}\b",
                cond, re.IGNORECASE)]
            if not cond_bad:
                continue
            out = sql[:start] + sql[end:]
            if not unknown_sql_columns(out, columns_by_table):
                return out.strip(), True
        return sql, False

    # ---- _find_bare_select_star (_find_bare_select_star) ----

    def _find_bare_select_star(self, sql):
        """Return a short description if `sql` is a bare `SELECT *` (no aggregate
        function, no GROUP BY). None otherwise. Never flags `SELECT t.*` that is
        accompanied by an aggregate."""
        m = re.search(r"\bselect\b([\s\S]*?)\bfrom\b", sql, re.IGNORECASE)
        if not m:
            return None
        select_part = m.group(1)
        if "*" not in select_part:
            return None
        has_agg = re.search(
            r"\b(?:count|sum|avg|average|min|max|stddev|std|variance|var_pop|var_samp|median|percentile_cont|percentile_disc)\s*\(",
            sql, re.IGNORECASE,
        )
        if has_agg:
            return None
        return "SELECT * with no aggregation"

    # ---- _find_suspicious_pk_joins (_find_suspicious_pk_joins) ----

    def _find_suspicious_pk_joins(self, sql):
        """Return equality join pairs that equate the PRIMARY KEYS of two
        DIFFERENT tables. In a normalized schema that is almost always a bug
        (e.g. `tracks.id = artists.id`); real joins go PK -> FK.

        Exception: a column that is both a member of a COMPOSITE primary key and
        a foreign key to the joined parent (e.g. order_details.product_id when
        order_details PK is (order_id, product_id)) is a legitimate FK join and
        is never flagged."""
        pk_of = {}
        for name, info in self.tables.items():
            _pk = set(info.get("primary_key", []) or info.get("inferred_primary_key", []) or [])
            # Generic composite members also count as key columns for the
            # PK=PK suspicious-join check (a composite member joined as an
            # FK to its parent is still exempted via the FK check below).
            try:
                _pk |= set(info.get("composite_primary_key", []) or [])
            except Exception:
                pass
            pk_of[name] = _pk
        # {table: {column: (referenced_table, referenced_column)}} from the FK edges.
        fk_of = {}
        for name, info in self.tables.items():
            for fk in info.get("foreign_keys", []):
                fk_of.setdefault(name, {})[fk["column"]] = (
                    fk["referenced_table"], fk["referenced_column"],
                )

        # Resolve aliases to table names: FROM x [AS] a, JOIN y [AS] b.
        alias_to_table = {}
        for m in re.finditer(
            r"\b(FROM|JOIN)\s+([\"'`]?)(\w+)\2\s+(?:AS\s+)?([a-zA-Z_]\w*)",
            sql,
            re.IGNORECASE,
        ):
            table, alias = m.group(3), m.group(4)
            alias_to_table[alias.lower()] = table
            if not m.group(4):
                alias_to_table[table.lower()] = table

        suspects = []
        # Capture each ON clause and the equality conditions inside it.
        for on_m in re.finditer(
            r"\bJOIN\s+([\"'`]?)(\w+)\1\s+(?:AS\s+)?([a-zA-Z_]\w*)\s+ON\s+(.*?)(?=\s+(?:JOIN|WHERE|GROUP|ORDER|LIMIT|;)|$)",
            sql,
            re.IGNORECASE,
        ):
            joined_table, joined_alias, on_clause = on_m.group(2), on_m.group(3).lower(), on_m.group(4)
            for eq in re.finditer(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)", on_clause):
                a, ca, b, cb = eq.groups()
                ta = alias_to_table.get(a.lower()) or a
                tb = alias_to_table.get(b.lower()) or b
                if ta == tb:
                    continue
                if ca in pk_of.get(ta, set()) and cb in pk_of.get(tb, set()):
                    if (ca in fk_of.get(ta, {}) and fk_of[ta][ca] == (tb, cb)) or (
                        cb in fk_of.get(tb, {}) and fk_of[tb][cb] == (ta, ca)
                    ):
                        continue
                    suspects.append(f"{ta}.{ca} = {tb}.{cb} (joins primary keys of unrelated tables)")
        return suspects

    # ---- _find_fk_mismatch_joins (_find_fk_mismatch_joins) ----

    def _find_fk_mismatch_joins(self, sql):
        """Return join equalities where an FK column is joined to a table it does
        NOT reference. E.g. tracks.album_id (FK -> albums.id) joined to artists.id
        is wrong: the FK definition says it must join albums, not artists."""
        # {table: {column: (referenced_table, referenced_column)}}
        fk_of = {}
        for name, info in self.tables.items():
            for fk in info.get("foreign_keys", []):
                fk_of.setdefault(name, {})[fk["column"]] = (fk["referenced_table"], fk["referenced_column"])

        alias_to_table = {}
        for m in re.finditer(
            r"\b(FROM|JOIN)\s+([\"'`]?)(\w+)\2\s+(?:AS\s+)?([a-zA-Z_]\w*)",
            sql,
            re.IGNORECASE,
        ):
            table, alias = m.group(3), m.group(4)
            alias_to_table[alias.lower()] = table
            if not m.group(4):
                alias_to_table[table.lower()] = table

        suspects = []
        for on_m in re.finditer(
            r"\bJOIN\s+([\"'`]?)(\w+)\1\s+(?:AS\s+)?([a-zA-Z_]\w*)\s+ON\s+(.*?)(?=\s+(?:JOIN|WHERE|GROUP|ORDER|LIMIT|;)|$)",
            sql,
            re.IGNORECASE,
        ):
            on_clause = on_m.group(4)
            for eq in re.finditer(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)", on_clause):
                a, ca, b, cb = eq.groups()
                ta = alias_to_table.get(a.lower()) or a
                tb = alias_to_table.get(b.lower()) or b
                if ta == tb:
                    continue
                if ca in fk_of.get(ta, {}):
                    ref_table, ref_col = fk_of[ta][ca]
                    if ref_table != tb or ref_col != cb:
                        suspects.append(
                            f"{ta}.{ca} references {ref_table}.{ref_col} but is joined to {tb}.{cb}"
                        )
                elif cb in fk_of.get(tb, {}):
                    ref_table, ref_col = fk_of[tb][cb]
                    if ref_table != ta or ref_col != ca:
                        suspects.append(
                            f"{tb}.{cb} references {ref_table}.{ref_col} but is joined to {ta}.{ca}"
                        )
        return suspects

    # ---- _llm_unavailable (_llm_unavailable) ----

    def _llm_unavailable(self, exc):
        """True when the language-model provider is down or rate-limited, as
        opposed to a genuine SQL-generation problem we could repair."""
        msg = str(exc).lower()
        if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
            return True
        if any(k in msg for k in ("connection", "timed out", "timeout", "connect", "refused")):
            return True
        if "ollama" in msg and ("down" in msg or "refused" in msg or "connect" in msg):
            return True
        return False

    # ---- _generate_sql (_generate_sql) ----

    def _generate_sql(self, user_goal, join_path, kpi_map, ir=None, join_plan=None):
        schema_ddl = self._build_schema_ddl(join_path, full=False)
        if not schema_ddl:
            return "SELECT 1;"

        kpi_desc = ", ".join(k["description"] for k in kpi_map["kpis"]) or "none"

        ir_summary = ""
        if ir:
            bits = []
            if ir.get("aggregation"):
                bits.append(f"aggregation: {ir['aggregation']}")
            resolved_metrics = [m for m in ir.get("metrics", []) if m.get("resolved_expression")]
            if resolved_metrics:
                def _render_measure(m):
                    agg = m.get("aggregation")
                    expr = (m.get("resolved_expression") or "").strip()
                    if not expr:
                        return None
                    if expr.upper() == "COUNT(*)" or agg == "COUNT":
                        return "COUNT(*) (MANDATORY — count records, do not substitute SUM/AVG)"
                    if agg:
                        return f"{agg}({expr})"
                    return expr
                bits.append("resolved measures: " + ", ".join(
                    r for r in (_render_measure(m) for m in resolved_metrics) if r))
            if ir.get("dimensions"):
                bits.append("dimensions: " + ", ".join(
                    d["concept"] for d in ir["dimensions"]))
            if ir.get("time"):
                t = ir["time"]
                bits.append(
                    f"time: {t.get('constraint')} {t.get('value', '')} "
                    f"on {t.get('column') or 'the relevant date column'}")
            if ir.get("ranking"):
                r = ir["ranking"]
                bits.append(
                    f"ranking: top {r.get('limit', 'N')} by the measure "
                    f"({r['direction']})")
            if ir.get("filters"):
                bits.append("filters: " + ", ".join(
                    f"{f.get('column') or 'date'} {f['operator']} {f['value']}"
                    for f in ir["filters"]))
            if bits:
                ir_summary = (
                    "### Resolved goal plan (deterministic, treat as ground truth)\n"
                    + "\n".join(f"- {b}" for b in bits) + "\n"
                )

        join_plan_text = ""
        if join_plan and join_plan.get("edges"):
            lines = [
                f"  {e['left_table']}.{e['left_column']} = "
                f"{e['right_table']}.{e['right_column']} [{e.get('trust', 'declared')}]"
                for e in join_plan["edges"]
            ]
            join_plan_text = (
                "### Deterministic join plan (MUST be followed exactly)\n"
                "Join ONLY through these validated relationships:\n"
                + "\n".join(lines) + "\n"
            )

        if self.dialect == "sqlite":
            dialect_note = (
                "### SQLite notes\n"
                "Use standard SQLite syntax: strftime('%Y', col) / strftime('%Y-%m', col) "
                "for dates instead of EXTRACT, and || for concatenation.\n"
            )
        elif self.dialect == "mysql":
            dialect_note = (
                "### MySQL notes\n"
                "Quote identifiers with backticks when needed. Use DATE_FORMAT(col, '%Y') / "
                "DATE_FORMAT(col, '%Y-%m') for date grouping instead of EXTRACT/strftime. "
                "Use NOW()/CURDATE() for current time, LIKE (there is no ILIKE), LIMIT for "
                "paging, and CONCAT() instead of ||. Backslash is the string escape character.\n"
            )
        else:
            dialect_note = ""

        prompt = f"""
### Task
Generate a single {self.dialect} SQL query that answers the user's business goal.
User goal: {user_goal}
Aligned KPIs: {kpi_desc}
Dimensions: {', '.join(kpi_map['dimensions']) if kpi_map['dimensions'] else 'auto-detect'}

{ir_summary}
### Database Schema
The query will run on a database with the following schema:
{schema_ddl}
Preferred starting tables (inspect these first, but you may use any table
needed to answer the goal, joining via the FOREIGN KEY relationships above):
{join_path}
{join_plan_text}{dialect_note}
### SQL
Output only the final SQL statement. No explanations, no markdown, nothing after it.

### CRITICAL RULES
1. Aggregate functions must NEVER be nested (AVG(SUM(x)), SUM(COUNT(x)) are INVALID).
2. An average per group = SUM(x) / COUNT(DISTINCT key) or a subquery.
3. For "highest AND lowest" / "most and least" / "top and bottom" / "best and worst":
   do NOT use LIMIT 1. Return the full ranked list so both ends are present.
4. For "the highest" / "the lowest" / "top N": use ORDER BY + LIMIT.
5. Never add a trailing semicolon-only statement; a single trailing semicolon is fine.
6. NEVER assume a JOIN exists. If the question can be answered from ONE table,
   query ONLY that table with NO JOIN. JOINs are allowed ONLY through the
   validated relationships in the deterministic join plan above (or the
   FOREIGN KEY lines in the schema); with zero relationships the answer MUST
   be a single-table query.
7. For simple questions ("average X", "total X", "how many"), return exactly ONE
   aggregate column. Do NOT add extra aggregates (e.g. do not do SUM+AVG).
8. For "compare X and Y", return a simple GROUP BY or two columns, NOT a complex
   multi-join analysis. Keep queries under 30 words.

### QUERY PATTERNS — match the goal to the correct pattern:

#### COUNT pattern ("how many", "count of", "number of")
SELECT COUNT(*) FROM table;

#### TOTAL/SUM pattern ("total revenue", "sum of sales", "total amount")
SELECT SUM(column) FROM table;
For revenue: SUM(quantity * unit_price * (1 - COALESCE(discount, 0)))

#### AVERAGE pattern ("average order value", "mean price")
SELECT AVG(column) FROM table;

#### GROUP BY pattern ("revenue by category", "sales by region", "orders by country")
SELECT dimension, SUM(measure) FROM fact_table JOIN dimension_table GROUP BY dimension ORDER BY SUM(measure) DESC;

#### RANKING pattern ("top 10 products", "best customers", "highest revenue")
SELECT dimension, SUM(measure) FROM table GROUP BY dimension ORDER BY SUM(measure) DESC LIMIT N;

#### TREND/TIME SERIES pattern ("revenue over time", "monthly revenue", "trend")
SELECT date_trunc('month', date_col) AS month, SUM(measure) FROM table GROUP BY month ORDER BY month;

#### COMPARISON pattern ("compare sales between regions", "revenue by country")
SELECT dimension, SUM(measure) FROM table GROUP BY dimension ORDER BY SUM(measure) DESC;

#### ANTI-JOIN pattern ("products never ordered", "customers without orders", "items not sold")
SELECT t1.* FROM table1 t1 LEFT JOIN table2 t2 ON t1.key = t2.key WHERE t2.key IS NULL;

#### PERCENTAGE/SHARE pattern ("percentage of revenue by category")
SELECT dimension, SUM(measure) * 100.0 / SUM(SUM(measure)) OVER() AS pct FROM table GROUP BY dimension;

#### WINDOW FUNCTION pattern ("rank by revenue", "running total", "percentile")
Use ROW_NUMBER(), RANK(), SUM() OVER(), etc.

#### SUBQUERY pattern ("products above average price", "orders with revenue above median")
SELECT * FROM table WHERE column > (SELECT AVG(column) FROM table);

#### DISTINCT pattern ("how many unique customers", "list all countries")
SELECT COUNT(DISTINCT column) FROM table;
SELECT DISTINCT column FROM table;

#### NULL HANDLING ("products never ordered" = LEFT JOIN + IS NULL)
Always use LEFT JOIN ... WHERE t2.key IS NULL for anti-joins.

#### DATE FILTERING ("last year", "Q3", "this month", "2024")
Use WHERE date_col >= '2024-01-01' AND date_col < '2025-01-01' for year 2024.
Use date_trunc('quarter', date_col) for quarter filtering.
"""
        try:
            # Fast, bounded LLM call: if it exceeds a short cap we fall back
            # to the fully dynamic deterministic SQL (no hardcoded table/column
            # names) so any database query is handled rather than hanging.
            _timeout = 60 if getattr(self.llm, "provider", "local") == "local" else 20
            raw = self.llm.complete("sql", prompt, temperature=0.1, num_predict=400, timeout=_timeout)
            sql = self._clean_sql(raw)
            try:
                sql = self._validate_sql_columns(user_goal, sql, ir)
            except Exception as e:
                logger.warning(f"SQL validation error: {e}")
            return sql
        except Exception as exc:
            logger.warning(f"LLM SQL generation failed: {exc}.")
            # Try deterministic template-based SQL before giving up
            det = self._deterministic_sql(user_goal, join_path, kpi_map, ir)
            if det:
                return det
            # Always try the fallback SQL rather than giving up on timeout
            return self._fallback_sql(join_path)

    # ---- _validate_sql_columns (_validate_sql_columns) ----

    def _validate_sql_columns(self, goal, sql, ir):
        """Post-validate: fix wrong columns AND simplify multi-aggregate queries."""
        if not sql:
            return sql
        import re
        goal_l = goal.lower()
        # Detect intent
        agg_match = None
        for kw, agg in [("average", "AVG"), ("avg", "AVG"), ("mean", "AVG"),
                         ("total", "SUM"), ("sum", "SUM")]:
            if kw in goal_l:
                agg_match = agg
                break
        if not agg_match:
            return sql
        # Build column lookup from schema
        all_cols = {}
        tables_list = []
        if ir:
            tables_list = ir.get("required_tables", []) or []
        if not tables_list:
            tables_list = list(self.tables.keys())[:1]
        for table in tables_list:
            try:
                for c, dt in self._table_columns_norm(table):
                    all_cols[c.lower()] = (table, c)
            except Exception:
                pass
        if not all_cols:
            return sql
        # Extract candidate column from the goal
        stripped = re.sub(r'\b(average|avg|mean|total|sum|what|is|the|of|are|there|how|many|price|value)\b', ' ', goal_l)
        words = [w.strip("?.!,;:'\"") for w in stripped.split() if len(w.strip("?.!,;:'\"")) >= 3]
        target = None
        for w in words:
            if w in all_cols:
                target = all_cols[w]
                break
        if not target:
            # Try multi-word: "discounted price" -> "discounted_price"
            for i in range(len(words)):
                for j in range(i + 2, min(i + 4, len(words) + 1)):
                    candidate = "_".join(words[i:j])
                    if candidate in all_cols:
                        target = all_cols[candidate]
                        break
                if target:
                    break
        if not target:
            # Fallback: find any numeric column whose name partially matches goal words
            for w in words:
                for col_lower, val in all_cols.items():
                    parts = col_lower.split("_")
                    if w in parts:
                        target = val
                        break
                if target:
                    break
        if not target:
            return sql
        target_table, target_col = target
        # If multiple aggregates, simplify to just the requested one
        agg_count = len(re.findall(r'\b(AVG|SUM|COUNT)\s*\(', sql, re.IGNORECASE))
        if agg_count > 1:
            return f'SELECT {agg_match}("{target_col}") AS result FROM "{target_table}";'
        # Fix wrong column in the aggregate
        agg_pattern = re.compile(rf'{agg_match}\s*\(\s*["\']?(\w+)["\']?\s*\)', re.IGNORECASE)
        m = agg_pattern.search(sql)
        if m:
            sql_col = m.group(1).lower()
            if sql_col != target_col.lower():
                sql = sql[:m.start(1)] + target_col + sql[m.end(1):]
        return sql

    # ---- _table_columns_norm (_table_columns_norm) ----

    def _table_columns_norm(self, table):
        """[(name, data_type)] for a table in EITHER mapping shape.

        The schema mapping may carry columns as a dict {name: {data_type}} (the
        normalized GoalAgent shape) or as a list [{column, data_type}] (raw
        extraction shape). The old deterministic templates only handled the
        list shape, so single-table dict-shape datasets silently fell through
        to None. Shared path: every template below uses this.
        """
        info = self.tables.get(table, {}) or {}
        cols_raw = info.get("columns", [])
        out = []
        if isinstance(cols_raw, dict):
            for name, meta in cols_raw.items():
                dt = ""
                if isinstance(meta, dict):
                    dt = str(meta.get("data_type", ""))
                out.append((str(name), dt))
        elif isinstance(cols_raw, list):
            for c in cols_raw:
                if isinstance(c, dict):
                    out.append((str(c.get("column", "")), str(c.get("data_type", ""))))
                elif isinstance(c, str):
                    out.append((str(c), ""))
        return [(n, dt) for n, dt in out if n]

    def _qcol(self, table, col):
        """Dialect-aware qualified column reference (quotes identifiers)."""
        q = lambda n: self._quote(n, getattr(self, "dialect", "postgresql"))
        if table:
            return f"{q(table)}.{q(col)}"
        return q(col)

    def _qtab(self, table):
        return self._quote(table, getattr(self, "dialect", "postgresql"))

    def _best_measure_for_table(self, table, ir=None):
        """Best SUM-able measure for `table`: IR-resolved metric wins, else the
        schema's best-guess measure column (dimension-like numerics skipped).
        Generic, never hardcoded to a column name."""
        if ir:
            for m in ir.get("metrics", []) or []:
                if m.get("resolved_table") == table and m.get("resolved_column"):
                    agg = str(m.get("aggregation", "") or "SUM").upper()
                    if agg in ("SUM", "AVG", "MIN", "MAX"):
                        return m["resolved_column"]
                if m.get("resolved_table") == table and m.get("resolved_expression"):
                    expr = str(m["resolved_expression"] or "")
                    if expr and expr.upper() != "COUNT(*)" and "(" not in expr:
                        part = expr.split(".")[-1]
                        if part:
                            return part
        try:
            picked = self._pick_measure_column(table)
            if picked:
                return picked
        except Exception:
            pass
        for name, _dt in self._table_columns_norm(table):
            low = name.lower()
            if low == "id" or low.endswith("_id"):
                continue
            try:
                if self._classify_column(table, name) == "numeric" \
                        and not self._is_dimension_like(table, name):
                    return name
            except Exception:
                continue
        return None

    def _groupable_columns(self, table):
        """Dimension-like columns usable as GROUP BY keys (text, boolean-as-int
        flags, dimension-like numerics such as store/holiday_flag, dates).

        Shared path: TEXT-only detection missed numeric dimensions (Walmart
        Store/Holiday_Flag are bigint) and picked the date instead of the
        requested store. PK/FK/*_id columns are still excluded.
        """
        info = self.tables.get(table, {}) or {}
        pk = set(info.get("primary_key", []) or [])
        fk_cols = {fk.get("column") for fk in info.get("foreign_keys", []) or []}
        out = []
        for name, _dt in self._table_columns_norm(table):
            low = name.lower()
            if name in pk or name in fk_cols or low == "id" or low.endswith("_id"):
                continue
            try:
                if self._is_dimension_like(table, name):
                    out.append(name)
                    continue
            except Exception:
                pass
            try:
                if self._classify_column(table, name) in ("text", "date"):
                    out.append(name)
            except Exception:
                out.append(name)
        return out

    def _date_col_for_table(self, table):
        """(col, data_type) of the table's date column, TEXT-date aware."""
        for name, dt in self._table_columns_norm(table):
            try:
                if self._classify_column(table, name) == "date":
                    return name, dt
            except Exception:
                continue
        for name, dt in self._table_columns_norm(table):
            d = (dt or "").lower()
            if any(k in d for k in ("date", "time", "timestamp")) or "date" in name.lower():
                return name, dt
        return None, None

    def _month_expr(self, table, col, dtype):
        """Dialect-aware month truncation, TEXT-date safe (DD-MM-YYYY + ISO)."""
        try:
            from core.data_intelligence import month_trunc_expression as _mte
            return _mte(self._qcol(table, col), dtype,
                        getattr(self, "dialect", "postgresql"))
        except Exception:
            q = self._qcol(table, col)
            dialect = getattr(self, "dialect", "postgresql")
            if dialect == "mysql":
                return f"DATE_FORMAT({q}, '%Y-%m')"
            if dialect == "sqlite":
                return f"strftime('%Y-%m', {q})"
            return f"date_trunc('month', {q})"

    # ---- _deterministic_sql (_deterministic_sql) ----

    def _deterministic_sql(self, user_goal, join_path, kpi_map, ir=None):
        """Generate SQL deterministically (no LLM) by pattern-matching the
        user goal against the schema. Used as a fallback when the LLM fails."""
        goal = user_goal.lower().strip()
        relevant = [t for t in join_path if t in self.tables]
        if not relevant:
            return None

        def _find_table(patterns):
            for pat in patterns:
                for t in relevant:
                    if pat in t.lower():
                        return t
            for pat in patterns:
                for t in self.tables:
                    if pat in t.lower():
                        return t
            return None

        def _find_col(table, patterns):
            for c, _dt in self._table_columns_norm(table):
                for pat in patterns:
                    if pat in c.lower():
                        return c
            return None

        def _revenue_expr(table):
            """Build revenue expression for a table (quoted, dialect-aware)."""
            cols = [c for c, _dt in self._table_columns_norm(table)]
            price = next((c for c in cols if "price" in c.lower() and "unit" in c.lower()), None)
            qty = next((c for c in cols if "quantity" in c.lower() or "qty" in c.lower()), None)
            disc = next((c for c in cols if "discount" in c.lower()), None)
            if price and qty:
                expr = f'{self._qcol(None, qty)} * {self._qcol(None, price)}'
                if disc:
                    expr += f' * (1 - COALESCE({self._qcol(None, disc)}, 0))'
                return expr, table
            return None, None

        def _measure_sum(table):
            """SUM(<best measure>) for `table`, quoted; None when no measure."""
            best = self._best_measure_for_table(table, ir)
            if best:
                return f'SUM({self._qcol(None, best)})', best
            return None, None

        # --- COUNT pattern ---
        if any(kw in goal for kw in ("how many", "count", "number of")):
            # Dynamic: extract entity tokens from goal, match against schema table names
            goal_words = set(goal.split())
            entity_tokens = [w for w in goal_words
                            if len(w) > 2
                            and w not in ("how", "many", "count", "number", "the", "are",
                                          "there", "in", "of", "for", "with", "total", "sum")]
            t = None
            for tok in entity_tokens:
                t = _find_table([tok])
                if t:
                    break
            if not t:
                t = relevant[0]
            return f'SELECT COUNT(*) AS count FROM {self._qtab(t)};'

        # --- TOTAL/SUM pattern ---
        if any(kw in goal for kw in ("total", "sum", "overall")):
            # Try to find revenue-like pattern
            for t in relevant:
                expr, _ = _revenue_expr(t)
                if expr:
                    return f'SELECT SUM({expr}) AS total FROM {self._qtab(t)};'
            # Fallback to the resolved/best measure (shared path, not name lists)
            for t in relevant:
                sum_expr, _col = _measure_sum(t)
                if sum_expr:
                    return f'SELECT {sum_expr} AS total FROM {self._qtab(t)};'

        # --- AVERAGE pattern ---
        if any(kw in goal for kw in ("average", "avg", "mean")):
            fact_tables = [t for t in relevant if self._is_pure_fact_table(t)]
            if not fact_tables:
                fact_tables = [t for t in relevant
                              if len(self.tables.get(t, {}).get("columns", {})) > 3
                              and any(c.lower().endswith("_id") for c in self.tables.get(t, {}).get("columns", {}))]
            if fact_tables:
                ft = fact_tables[0]
                ft_info = self.tables.get(ft, {})
                ft_cols = list(ft_info.get("columns", {}))
                # Find the FK in the fact table that joins to another relevant table
                fk_col = next((c for c in ft_cols if c.lower().endswith("_id") and c.lower() != "id"), None)
                if fk_col:
                    # Find the dimension table this FK references
                    ref_table = None
                    for t2 in relevant:
                        if t2 == ft:
                            continue
                        t2_info = self.tables.get(t2, {})
                        t2_pk = next((c for c in t2_info.get("columns", {})
                                      if c.lower().endswith("_id") or c.lower() == "id"), None)
                        if t2_pk and t2_pk.lower() == fk_col.lower():
                            ref_table = t2
                            break
                    if not ref_table:
                        ref_table = next((t2 for t2 in relevant if t2 != ft), None)
                    if ref_table:
                        expr, _ = _revenue_expr(ft)
                        ref_pk = next((c for c in self.tables.get(ref_table, {}).get("columns", {})
                                       if c.lower().endswith("_id") or c.lower() == "id"), None)
                        if expr and ref_pk:
                            return (f'SELECT SUM({expr}) / COUNT(DISTINCT {self._qcol(ref_table, ref_pk)}) AS average '
                                    f'FROM {self._qtab(ft)} JOIN {self._qtab(ref_table)} ON {self._qcol(ref_table, ref_pk)} = {self._qcol(ft, fk_col)};')
            for t in relevant:
                # Goal-specific: try to find the column named in the user's question
                all_cols = {c.lower(): c for c, _dt in self._table_columns_norm(t)}
                goal_words = goal.replace("average", "").replace("avg", "").replace("mean", "").replace("of", "").replace("the", "").split()
                target_col = None
                for w in goal_words:
                    w = w.strip()
                    if len(w) >= 3 and w in all_cols:
                        target_col = all_cols[w]
                        break
                if target_col:
                    return f'SELECT AVG({self._qcol(None, target_col)}) AS average FROM {self._qtab(t)};'
                sum_expr, _col = _measure_sum(t)
                if sum_expr:
                    best = self._best_measure_for_table(t, ir)
                    return f'SELECT AVG({self._qcol(None, best)}) AS average FROM {self._qtab(t)};'

        # --- TREND/TIME SERIES pattern (TEXT-date safe) ---
        if any(kw in goal for kw in ("trend", "over time", "monthly", "daily", "weekly", "yearly", "by month", "by year", "by day")):
            for t in relevant:
                date_col, date_dtype = self._date_col_for_table(t)
                if not date_col:
                    continue
                month_expr = self._month_expr(t, date_col, date_dtype)
                expr, _ = _revenue_expr(t)
                if expr:
                    return (f"SELECT {month_expr} AS period, "
                            f'SUM({expr}) AS value '
                            f'FROM {self._qtab(t)} '
                            f'GROUP BY period ORDER BY period;')
                sum_expr, _col = _measure_sum(t)
                if sum_expr:
                    return (f"SELECT {month_expr} AS period, "
                            f'{sum_expr} AS value '
                            f'FROM {self._qtab(t)} '
                            f'GROUP BY period ORDER BY period;')
                # No measure: count rows over time (still TEXT-date safe).
                return (f"SELECT {month_expr} AS period, "
                        f'COUNT(*) AS value '
                        f'FROM {self._qtab(t)} '
                        f'GROUP BY period ORDER BY period;')

        def _resolve_group_col(t):
            """Goal-named groupable column wins; else first groupable."""
            try:
                dims = (ir or {}).get("dimensions") or []
                for d in dims:
                    if d.get("resolved_table") == t and d.get("resolved_column"):
                        return d["resolved_column"]
            except Exception:
                pass
            groupables = self._groupable_columns(t)
            if not groupables:
                return None
            gl = " " + goal + " "
            for c in groupables:
                parts = [p for p in c.lower().split("_") if p]
                if any(p in gl or p.rstrip("s") in gl or (p + "s") in gl for p in parts):
                    return c
            return groupables[0]

        # --- GROUP BY / BY pattern ---
        if any(kw in goal for kw in (" by ", " per ", "breakdown", "distribution")):
            for t in relevant:
                cat = _resolve_group_col(t)
                if not cat:
                    continue
                expr, _ = _revenue_expr(t)
                if expr:
                    return (f'SELECT {self._qcol(t, cat)}, SUM({expr}) AS value '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY value DESC;')
                sum_expr, _col = _measure_sum(t)
                if sum_expr:
                    return (f'SELECT {self._qcol(t, cat)}, {sum_expr} AS value '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY value DESC;')
                return (f'SELECT {self._qcol(t, cat)}, COUNT(*) AS value '
                        f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY value DESC;')

        # --- RANKING pattern ---
        if any(kw in goal for kw in ("top", "best", "highest", "most", "leading", "largest")):
            for t in relevant:
                cat = _resolve_group_col(t)
                if not cat:
                    continue
                expr, _ = _revenue_expr(t)
                if expr:
                    return (f'SELECT {self._qcol(None, cat)}, SUM({expr}) AS value '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(None, cat)} ORDER BY value DESC LIMIT 10;')
                sum_expr, _col = _measure_sum(t)
                if sum_expr:
                    return (f'SELECT {self._qcol(None, cat)}, {sum_expr} AS value '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(None, cat)} ORDER BY value DESC LIMIT 10;')
                return (f'SELECT {self._qcol(None, cat)}, COUNT(*) AS value '
                        f'FROM {self._qtab(t)} GROUP BY {self._qcol(None, cat)} ORDER BY value DESC LIMIT 10;')

        # --- COMPARISON pattern (incl. holiday vs non-holiday) ---
        if any(kw in goal for kw in ("compare", "vs", "versus", "between")):
            for t in relevant:
                cat = _resolve_group_col(t)
                if not cat:
                    continue
                expr, _ = _revenue_expr(t)
                if expr:
                    return (f'SELECT {self._qcol(t, cat)}, SUM({expr}) AS value '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY value DESC;')
                sum_expr, _col = _measure_sum(t)
                if sum_expr:
                    return (f'SELECT {self._qcol(t, cat)}, {sum_expr} AS value '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY value DESC;')
                return (f'SELECT {self._qcol(t, cat)}, COUNT(*) AS value '
                        f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY value DESC;')

        # --- ANTI-JOIN pattern ---
        if any(kw in goal for kw in ("never", "without", "not sold", "no orders", "no sales", "no records")):
            fact_tables = [t for t in relevant if self._is_pure_fact_table(t)]
            if fact_tables and len(relevant) >= 2:
                dim_table = [t for t in relevant if t not in fact_tables]
                if dim_table:
                    dt, ft = dim_table[0], fact_tables[0]
                    dt_info = self.tables.get(dt, {})
                    ft_info = self.tables.get(ft, {})
                    dt_pk = next((c for c in dt_info.get("columns", {})
                                   if c.lower().endswith("_id") or c.lower() == "id"), None)
                    ft_fk = next((c for c in ft_info.get("columns", {})
                                   if c.lower() == f"{dt.lower()}_id" or c.lower().endswith("_id")), None)
                    if dt_pk and ft_fk:
                        return (f'SELECT t1.* FROM {self._qtab(dt)} t1 '
                                f'LEFT JOIN {self._qtab(ft)} t2 ON t1.{self._qcol(None, dt_pk)} = t2.{self._qcol(None, ft_fk)} '
                                f'WHERE t2.{self._qcol(None, ft_fk)} IS NULL LIMIT 50;')

        # --- PERCENTAGE pattern ---
        if any(kw in goal for kw in ("percentage", "percent", "share", "proportion")):
            for t in relevant:
                cat = _resolve_group_col(t)
                if not cat:
                    continue
                expr, _ = _revenue_expr(t)
                sum_expr, _col = _measure_sum(t)
                agg = expr or (sum_expr.replace("SUM(", "", 1)[:-1] if sum_expr else None)
                if cat and agg:
                    return (f'SELECT {self._qcol(t, cat)}, '
                            f'SUM({agg}) * 100.0 / SUM(SUM({agg})) OVER() AS percentage '
                            f'FROM {self._qtab(t)} GROUP BY {self._qcol(t, cat)} ORDER BY percentage DESC;')

        # --- BARE MEASURE fallback ("What are my sales?") ---
        # A sales/revenue-flavoured question with no other pattern still needs
        # SUM(main measure), never None and never SELECT *. Shared path: the IR
        # resolved metric wins so Walmart binds weekly_sales on every dialect.
        try:
            dims = (ir or {}).get("dimensions") or []
        except Exception:
            dims = []
        if not dims:
            for t in relevant:
                sum_expr, _col = _measure_sum(t)
                if sum_expr and any(kw in goal for kw in (
                        "sale", "revenue", "profit", "amount", "total", "value",
                        "quantity", "qty", "price", "cost", "weekly")):
                    return f'SELECT {sum_expr} AS total FROM {self._qtab(t)};'

        return None

    # ---- _semantic_validate_sql (_semantic_validate_sql) ----

    def _semantic_validate_sql(self, ir, sql, join_path, join_plan=None):
        """Semantic SQL validation (spec §9/§10): the final SQL must actually
        implement the resolved Goal IR â€” required tables in FROM, measures
        aggregated, filters/time/ranking present â€” and must respect the
        explicit deterministic join plan.

        Returns (issues, warnings). Empty issues = PASS. Deterministic; the
        LLM is NOT the authority on the plan. Runs after every repair so a
        repaired query is re-validated before execution.
        """
        issues = []
        warnings = []
        if not ir or not sql:
            return issues, warnings
        struct = self._sql_structure(sql)
        in_from = {t.lower() for t in struct["in_from"]}
        sql_lower = sql.lower()
        sql_upper = sql.upper()

        required = set()
        for m in ir.get("metrics", []):
            if m.get("resolved_table"):
                required.add(m["resolved_table"])
        for d in ir.get("dimensions", []):
            if d.get("resolved_table"):
                required.add(d["resolved_table"])
        if not required and join_path:
            required.add(join_path[0])
        missing = [t for t in sorted(required) if t.lower() not in in_from]
        if missing:
            issues.append(
                f"required table(s) {', '.join(missing)} are missing from FROM/JOIN"
            )

        wants_count = ir.get("aggregation") == "COUNT" or any(
            str(m.get("aggregation", "")).upper() == "COUNT"
            for m in ir.get("metrics", [])
        )
        if wants_count and "COUNT(" not in sql_upper:
            issues.append("the goal asks for a count but the SQL has no COUNT(...)")
        elif ir.get("aggregation") and not re.search(
                r"\b(SUM|AVG|MIN|MAX|COUNT)\s*\(", sql_upper):
            issues.append(
                f"the goal requires {ir['aggregation']} aggregation but the SQL "
                "has no aggregate function"
            )

        for m in ir.get("metrics", []):
            agg = m.get("aggregation")
            col = m.get("resolved_column")
            if not agg:
                continue
            if agg.upper() == "COUNT":
                if "COUNT(" not in sql_upper:
                    issues.append(
                        "the resolved metric requires a COUNT of records "
                        "but the SQL has no COUNT(...)"
                    )
                continue
            if f"{agg.upper()}(" not in sql_upper:
                issues.append(
                    f"the resolved metric requires {agg.upper()} over "
                    f"{m.get('resolved_expression')} but the SQL has no {agg.upper()}"
                )
            elif col and col.lower() not in sql_lower:
                issues.append(
                    f"the resolved measure column {m.get('resolved_expression')} "
                    "is not referenced by the SQL"
                )

        where_l = self._where_clause(sql).lower()
        for f in ir.get("filters", []):
            col = f.get("column")
            if not col:
                continue
            token = col.split(".")[-1].lower()
            if token and token not in where_l:
                issues.append(
                    f"the requested filter on {col} is not applied in the SQL WHERE clause"
                )

        # A bare period granularity ("weekly" in "weekly sales", "monthly
        # trend" with no year/value) is a grouping hint, not a WHERE constraint:
        # it must not fail a scalar aggregate whose measure name merely
        # contains the period word. Enforce the date-column requirement only
        # when the goal carries an actual time constraint (a value/year or an
        # explicit date filter); otherwise record a warning.
        if ir.get("time") and ir["time"].get("column"):
            date_token = ir["time"]["column"].split(".")[-1].lower()
            has_time_constraint = (
                ir["time"].get("value") is not None
                or any(f.get("column") for f in ir.get("filters", []))
            )
            if date_token and date_token not in sql_lower:
                if has_time_constraint:
                    issues.append(
                        "the requested time constraint is not applied to any date column"
                    )
                else:
                    warnings.append(
                        "the goal hints at a time granularity but the SQL does "
                        "not reference the date column"
                    )

        if ir.get("ranking"):
            if ir["ranking"].get("limit") is not None:
                if not re.search(r"\bLIMIT\s+\d+", sql_upper):
                    issues.append(
                        "the goal asks for a top/bottom N but the SQL has no LIMIT"
                    )
            if not re.search(r"\bORDER\s+BY\b", sql_upper):
                issues.append(
                    "the goal asks for a ranked result but the SQL has no ORDER BY"
                )

        if join_plan and join_plan.get("edges"):
            joined_pairs = set()
            for j in self._extract_sql_joins(sql):
                joined_pairs.add((j["left_table"].lower(), j["right_table"].lower()))
                joined_pairs.add((j["right_table"].lower(), j["left_table"].lower()))
            plan_nodes = {t.lower() for t in join_plan.get("nodes", [])}
            for e in join_plan["edges"]:
                pair = (e["left_table"].lower(), e["right_table"].lower())
                if pair not in joined_pairs:
                    issues.append(
                        f"the planned join {e['left_table']}.{e['left_column']} = "
                        f"{e['right_table']}.{e['right_column']} is missing from the SQL"
                    )
            extra = [t for t in in_from if t not in plan_nodes]
            if extra:
                warnings.append(
                    f"SQL uses table(s) {', '.join(sorted(extra))} outside the "
                    "deterministic join plan"
                )

        # ---- GROUP-BY granularity (spec §12 / Fix 3: AOV over-grouping) ----
        # A scalar overall aggregate (e.g. "average order value", "total sales")
        # must yield a single row: the outer SELECT must NOT carry a GROUP BY.
        # An LLM frequently over-groups AOV (e.g. AVG(total) GROUP BY customer_id),
        # splitting the single scalar metric into per-group rows and returning the
        # wrong answer. Flag it so the query is repaired to a single-row aggregate.
        #
        # Per-entity / "top N" / "by X" / "per X" / comparison goals are NOT
        # flagged: they carry intent ranking/comparison/distribution/trend, a
        # ranking block, a comparison block, or explicit dimensions, so a GROUP BY
        # is correct for them.
        #
        # Only the OUTERMOST (parenthesis-depth-0) GROUP BY is considered, so a
        # correct per-order AOV subquery
        #   SELECT AVG(v) FROM (SELECT SUM(x) AS v FROM ... GROUP BY order_id) t
        # is not mis-flagged -- its GROUP BY lives inside a subquery.
        _gb_match = re.search(r"\bGROUP\s+BY\s+", sql, re.IGNORECASE)
        _outer_gb = []
        if _gb_match:
            _depth = sql[:_gb_match.start()].count("(") - sql[:_gb_match.start()].count(")")
            if _depth == 0:
                _outer_gb = self._extract_sql_group_by(sql)
        if (
            _outer_gb
            and ir.get("aggregation")
            and ir.get("intent") == "summary"
            and not ir.get("ranking")
            and not ir.get("comparison")
            and not ir.get("dimensions")
            and re.search(r"\b(SUM|AVG|MIN|MAX|COUNT)\s*\(", sql_upper)
        ):
            issues.append(
                "the goal asks for an overall aggregate (no breakdown) but the SQL "
                "groups by "
                + ", ".join(_outer_gb)
                + " (over-grouping: a single aggregate metric must not be split "
                "into per-group rows)"
            )

        for w in self._detect_fan_out(ir, join_plan, in_from):
            warnings.append(w)
        return issues, warnings

    # ---- _detect_fan_out (_detect_fan_out) ----

    def _detect_fan_out(self, ir, join_plan, in_from):
        """Spec §18: warn when a SUM/AVG metric is summed over a table that is
        an ANCESTOR of the row-grain table. In a many-to-one chain such as
        customers -> orders -> order_items, summing an order_items grain by a
        customers-level value would multiply it by the number of matching child
        rows (row fan-out / double counting). Deterministic; warning only.
        """
        if not ir or not join_plan or not join_plan.get("edges"):
            return []
        metrics = [m for m in ir.get("metrics", []) if m.get("resolved_table")]
        if not metrics:
            return []
        sums = [
            m for m in metrics
            if str(m.get("aggregation", "")).upper() in ("SUM", "AVG")
        ]
        if not sums:
            return []
        grain = None
        for d in ir.get("dimensions", []):
            if d.get("resolved_table"):
                grain = d["resolved_table"]
                break
        if not grain:
            grain = next(iter(in_from)) if in_from else None
        if not grain:
            return []
        child_to_parent = {}
        for e in join_plan["edges"]:
            if e.get("cardinality") == "many_to_one":
                child_to_parent.setdefault(
                    e["left_table"].lower(), set()
                ).add(e["right_table"].lower())
        if not child_to_parent:
            return []
        warnings = []
        for m in sums:
            mt = m["resolved_table"].lower()
            if mt == grain.lower():
                continue
            if mt not in in_from or grain.lower() not in in_from:
                continue
            # Walk up from the grain table along many-to-one (child -> parent)
            # edges. If we reach the metric's table, the metric table is an
            # ancestor of the grain -> row fan-out is possible.
            seen, stack = {grain.lower()}, [grain.lower()]
            reached = False
            while stack:
                cur = stack.pop()
                for parent in child_to_parent.get(cur, []):
                    if parent == mt:
                        reached = True
                        break
                    if parent not in seen:
                        seen.add(parent)
                        stack.append(parent)
                if reached:
                    break
            if reached:
                warnings.append(
                    f"possible row fan-out: the {m.get('aggregation')} over "
                    f"{m.get('resolved_expression') or m.get('resolved_column')} is "
                    f"taken at table {m['resolved_table']}, an ancestor of the row "
                    f"grain table {grain}; the metric may be multiplied across "
                    "matching child rows"
                )
        return warnings

    # ---- _fallback_sql (_fallback_sql) ----

    def _fallback_sql(self, join_path):
        """Smart template-based fallback when the LLM fails.
        Tries to match the user goal to common SQL patterns."""
        relevant = [t for t in join_path if t in self.tables]
        if not relevant:
            if self.dialect == "sqlite":
                return "SELECT name FROM sqlite_master WHERE type='table' LIMIT 10;"
            return "SELECT table_name FROM information_schema.tables LIMIT 10;"

        goal = (getattr(self, "_active_original_goal", "") or "").lower()

        NUMERIC_TYPES = {"int", "integer", "bigint", "decimal", "numeric", "real",
                        "double precision", "float", "money", "smallint"}

        # Anti-join: "never ordered", "without orders", "not sold"
        if any(kw in goal for kw in ("never", "without", "not sold", "not ordered", "no orders", "no sales")):
            fact_tables = [t for t in relevant if self._is_pure_fact_table(t)]
            if fact_tables and len(relevant) >= 2:
                dim_table = [t for t in relevant if t not in fact_tables]
                if dim_table:
                    dt = dim_table[0]
                    ft = fact_tables[0]
                    dt_info = self.tables.get(dt, {})
                    ft_info = self.tables.get(ft, {})
                    dt_pk = next((c for c in dt_info.get("columns", {})
                                   if c.lower().endswith("_id") or c.lower() == "id"), None)
                    ft_fk = next((c for c in ft_info.get("columns", {})
                                   if c.lower() == f"{dt.lower()}_id" or c.lower().endswith("_id")), None)
                    if dt_pk and ft_fk:
                        return (f'SELECT t1.* FROM "{dt}" t1 '
                                f'LEFT JOIN "{ft}" t2 ON t1."{dt_pk}" = t2."{ft_fk}" '
                                f'WHERE t2."{ft_fk}" IS NULL LIMIT 50;')

        # COUNT pattern
        if any(kw in goal for kw in ("how many", "count", "number of")):
            table = relevant[0]
            return f'SELECT COUNT(*) AS count FROM "{table}";'

        # TOTAL/SUM pattern
        if any(kw in goal for kw in ("total", "sum", "overall")):
            for t in relevant:
                num_cols = [c for c, dt in self._table_columns_norm(t)
                            if dt.upper() in NUMERIC_TYPES or any(k in dt.lower() for k in ("int", "decimal", "numeric", "float", "real", "double", "money"))
                            and not c.lower().endswith("_id") and c.lower() != "id"]
                if num_cols:
                    return f'SELECT SUM("{num_cols[0]}") AS total FROM "{t}";'

        # AVERAGE pattern — try to match the specific column the user asked about
        if any(kw in goal for kw in ("average", "avg", "mean")):
            for t in relevant:
                all_cols = {c.lower(): c for c, _dt in self._table_columns_norm(t)}
                # Try to find the column named in the goal (e.g. "average rating" -> "rating")
                goal_words = goal.replace("average", "").replace("avg", "").replace("mean", "").replace("of", "").replace("the", "").split()
                target_col = None
                for w in goal_words:
                    w = w.strip()
                    if len(w) >= 3 and w in all_cols:
                        target_col = all_cols[w]
                        break
                if target_col:
                    return f'SELECT AVG("{target_col}") AS average FROM "{t}";'
                # Fallback: pick any numeric column
                num_cols = [c for c, dt in self._table_columns_norm(t)
                            if dt.upper() in NUMERIC_TYPES or any(k in dt.lower() for k in ("int", "decimal", "numeric", "float", "real", "double", "money"))
                            and not c.lower().endswith("_id") and c.lower() != "id"]
                if num_cols:
                    return f'SELECT AVG("{num_cols[0]}") AS average FROM "{t}";'

        # GROUP BY pattern ("by category", "by region", "by country")
        by_match = None
        for kw in (" by ", " per ", " breakdown", " distribution"):
            if kw in goal:
                by_match = kw.strip()
                break

        if by_match:
            for t in relevant:
                all_cols = self._table_columns_norm(t)
                cat_cols = [c for c, dt in all_cols
                            if dt.upper() in TEXT_TYPES or any(k in dt.lower() for k in ("char", "text", "varchar"))
                            and not c.lower().endswith("_id") and c.lower() != "id"]
                num_cols = [c for c, dt in all_cols
                            if dt.upper() in NUMERIC_TYPES or any(k in dt.lower() for k in ("int", "decimal", "numeric", "float", "real", "double", "money"))
                            and not c.lower().endswith("_id") and c.lower() != "id"]
                if cat_cols and num_cols:
                    cat = cat_cols[0]
                    num = num_cols[0]
                    return (f'SELECT t."{cat}", SUM("{num}") AS total '
                            f'FROM "{t}" t GROUP BY t."{cat}" ORDER BY total DESC;')

        # RANKING pattern ("top", "best", "highest", "most")
        if any(kw in goal for kw in ("top", "best", "highest", "most", "leading", "largest")):
            for t in relevant:
                all_cols = self._table_columns_norm(t)
                name_cols = [c for c, dt in all_cols
                             if dt.upper() in TEXT_TYPES or any(k in dt.lower() for k in ("char", "text", "varchar"))
                             and not c.lower().endswith("_id") and c.lower() != "id"]
                num_cols = [c for c, dt in all_cols
                            if dt.upper() in NUMERIC_TYPES or any(k in dt.lower() for k in ("int", "decimal", "numeric", "float", "real", "double", "money"))
                            and not c.lower().endswith("_id") and c.lower() != "id"]
                if name_cols and num_cols:
                    name = name_cols[0]
                    num = num_cols[0]
                    return (f'SELECT "{name}", SUM("{num}") AS total '
                            f'FROM "{t}" GROUP BY "{name}" ORDER BY total DESC LIMIT 10;')

        # Default: SELECT from the first table
        return f'SELECT * FROM "{relevant[0]}" LIMIT 50;'

    # ---- _row_counts (_row_counts) ----

    def _row_counts(self):
        """Count rows per table (cached per agent) so a genuinely empty table
        can be told apart from a faulty query."""
        if self._row_counts_cache is not None:
            return self._row_counts_cache
        counts = {}
        try:
            with self.engine.connect() as conn:
                for table_name in self.tables:
                    try:
                        from core.relational import quote_identifier
                        result = conn.execute(text(f'SELECT count(*) FROM {quote_identifier(table_name, "postgresql")}'))
                        counts[table_name] = int(result.scalar() or 0)
                    except Exception:
                        counts[table_name] = -1
        except Exception:
            pass
        self._row_counts_cache = counts
        return counts

