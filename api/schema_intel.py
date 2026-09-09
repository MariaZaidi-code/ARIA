"""Shared schema intelligence — dynamic column classification using data_type.

Used by both KPI routes and Insights engine. Zero hardcoded table/column names.
Classifies columns by their actual database data_type from the schema metadata.
"""

# ── Type classification (fully dynamic from data_type) ────────────────────

NUMERIC_TYPES = {
    "smallint", "integer", "bigint", "decimal", "numeric",
    "real", "double precision", "float", "money",
    "tinyint", "int",
}
DATETIME_TYPES = {
    "date", "time", "timestamp", "timestamp without time zone",
    "timestamp with time zone", "datetime", "smalldatetime",
}
TEXT_TYPES = {
    "character varying", "varchar", "character", "char",
    "text", "citext", "ltree", "uuid",
}
BINARY_TYPES = {"bytea", "blob", "binary", "varbinary"}

# Amount-like column name hints (used to prefer revenue columns over IDs)
AMOUNT_HINTS = (
    "price", "cost", "amount", "total", "sum", "revenue",
    "sales", "income", "expense", "profit", "value",
    "quantity", "qty", "discount", "freight", "tax",
    "payment", "balance", "weight", "unit_price", "margin",
    "turnover", "billing", "charge", "fee", "rate",
)


def classify_type(data_type: str) -> str:
    """Classify a database column type into a semantic category."""
    dt = data_type.lower().strip()
    if dt in NUMERIC_TYPES or any(k in dt for k in (
        "int", "decimal", "numeric", "float", "real", "double", "money"
    )):
        return "numeric"
    if dt in DATETIME_TYPES or any(k in dt for k in ("date", "time", "timestamp")):
        return "datetime"
    if dt in TEXT_TYPES or any(k in dt for k in ("char", "text", "varchar", "uuid")):
        return "text"
    if dt in BINARY_TYPES:
        return "binary"
    return "other"


def _safe_name(name: str, dialect: str = "postgresql") -> str:
    """Quote an identifier for the given dialect."""
    if dialect == "mysql":
        return f"`{name}`"
    return f'"{name}"'


def _run_sql(conn, sql: str, limit: int = 500):
    """Execute read-only SQL and return (columns, rows_as_dicts)."""
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(limit)
        cur.close()
        return cols, [dict(zip(cols, row)) for row in rows]
    except Exception:
        return [], []


class SchemaIntelligence:
    """Analyze any database schema using data_type, PKs, and FKs.

    Works with any PostgreSQL/MySQL/SQLite database. Zero hardcoded assumptions
    about table names, column names, or schema structure.
    """

    def __init__(self, mapping: dict):
        self.mapping = mapping
        self.tables = mapping.get("tables", {})
        self.fks = mapping.get("declared_relationships", [])
        self.edges = mapping.get("relationship_edges", [])

        self._pk_map = {}
        self._fk_map = {}
        self._col_types = {}
        self._col_category = {}
        self._table_categories = {}

        self._build_lookups()

    def _build_lookups(self):
        for tname, tinfo in self.tables.items():
            pks = tinfo.get("primary_key", []) or tinfo.get("inferred_primary_key", [])
            self._pk_map[tname] = pks

            cols_raw = tinfo.get("columns", [])
            col_names = []
            if isinstance(cols_raw, list):
                if len(cols_raw) > 0 and isinstance(cols_raw[0], str):
                    col_names = [str(c).strip() for c in cols_raw if c]
                    synthetic_cols = [{"column": name, "data_type": "unknown"} for name in col_names]
                    cols_raw = synthetic_cols
                else:
                    col_names = [str(c.get("column", "")).strip() for c in cols_raw if isinstance(c, dict) and c.get("column")]
            elif isinstance(cols_raw, dict):
                col_names = [str(k).strip() for k in cols_raw.keys() if k]
                synthetic_cols = [{"column": str(k).strip(), "data_type": "unknown"} for k in cols_raw.keys()]
                cols_raw = synthetic_cols

            cat_map = {"numeric": [], "text": [], "datetime": [], "binary": [], "other": []}
            for c in cols_raw:
                if isinstance(c, dict):
                    cname = str(c.get("column", "")).strip()
                    dtype = str(c.get("data_type", "")).lower().strip()
                elif isinstance(c, str):
                    cname = str(c).strip()
                    dtype = "unknown"
                else:
                    continue
                if not cname:
                    continue
                cat = classify_type(dtype)
                self._col_types.setdefault(tname, {})[cname] = dtype
                self._col_category.setdefault(tname, {})[cname] = cat
                cat_map[cat].append(cname)

            if not cat_map.get("numeric") and col_names:
                cat_map = {"numeric": [], "text": [], "datetime": [], "binary": [], "other": []}
                for cname in col_names:
                    low = cname.lower()
                    if any(h in low for h in ("amount", "price", "cost", "total", "value", "revenue", "sales", "qty", "quantity", "count")):
                        cat_map["numeric"].append(cname)
                    elif any(h in low for h in ("date", "time", "created", "updated", "timestamp")):
                        cat_map["datetime"].append(cname)
                    elif low.endswith("_id") or low in ("id", "key", "code"):
                        cat_map["other"].append(cname)
                    else:
                        cat_map["text"].append(cname)
                for cname in col_names:
                    low = cname.lower()
                    if cname in cat_map.get("numeric", []):
                        cat = "numeric"
                    elif cname in cat_map.get("datetime", []):
                        cat = "datetime"
                    elif cname in cat_map.get("binary", []):
                        cat = "binary"
                    elif cname in cat_map.get("other", []):
                        cat = "other"
                    else:
                        cat = "text"
                    self._col_types.setdefault(tname, {})[cname] = "inferred"
                    self._col_category.setdefault(tname, {})[cname] = cat
            self._table_categories[tname] = cat_map

        for fk in self.fks:
            t = fk.get("table_name", "")
            col = fk.get("column_name", "")
            ref_t = fk.get("references_table", "")
            ref_c = fk.get("references_column", "")
            if t and col and ref_t and ref_c:
                self._fk_map.setdefault(t, []).append((col, ref_t, ref_c))

    def get_numeric_cols(self, table: str) -> list:
        return self._table_categories.get(table, {}).get("numeric", [])

    def get_text_cols(self, table: str) -> list:
        return self._table_categories.get(table, {}).get("text", [])

    def get_datetime_cols(self, table: str) -> list:
        return self._table_categories.get(table, {}).get("datetime", [])

    def get_pk(self, table: str) -> list:
        return self._pk_map.get(table, [])

    def get_fks(self, table: str) -> list:
        return self._fk_map.get(table, [])

    def get_col_names(self, table: str) -> list:
        cols_raw = self.tables.get(table, {}).get("columns", [])
        if isinstance(cols_raw, list):
            return [c.get("column", "") for c in cols_raw if isinstance(c, dict)]
        elif isinstance(cols_raw, dict):
            return list(cols_raw.keys())
        return []

    def is_fact_table(self, table: str) -> bool:
        numerics = self.get_numeric_cols(table)
        fks = self.get_fks(table)
        return len(numerics) >= 1 and len(fks) >= 1

    def is_dimension_table(self, table: str) -> bool:
        texts = self.get_text_cols(table)
        pks = self.get_pk(table)
        outgoing_fks = self.get_fks(table)
        return len(texts) >= 1 and len(pks) >= 1 and len(outgoing_fks) <= 1

    def find_best_measure(self, table: str):
        """Pick the most analytically useful numeric column (prefer amounts over IDs)."""
        numerics = self.get_numeric_cols(table)
        if not numerics:
            return None
        pks = set(self.get_pk(table))
        fk_cols = set(fk[0] for fk in self.get_fks(table))

        # Tier 1: amount-like names, not PK/FK
        tier1 = [c for c in numerics
                 if c not in pks and c not in fk_cols
                 and any(h in c.lower() for h in AMOUNT_HINTS)]
        if tier1:
            return tier1[0]

        # Tier 2: non-PK/FK, non-ID columns
        tier2 = [c for c in numerics
                 if c not in pks and c not in fk_cols
                 and not c.lower().endswith("_id")
                 and not c.lower() == "id"]
        if tier2:
            return tier2[0]

        return None

    def find_all_measures(self, table: str):
        """Return all usable numeric measure columns for a table."""
        numerics = self.get_numeric_cols(table)
        pks = set(self.get_pk(table))
        fk_cols = set(fk[0] for fk in self.get_fks(table))
        return [c for c in numerics
                if c not in pks and c not in fk_cols
                and not c.lower().endswith("_id")
                and not c.lower() == "id"]

    def find_best_dimension(self, table: str):
        """Pick the most descriptive text column for grouping (skip IDs)."""
        texts = self.get_text_cols(table)
        if not texts:
            return None
        pks = set(self.get_pk(table))
        fk_cols = set(fk[0] for fk in self.get_fks(table))
        usable = [c for c in texts
                  if c not in pks and c not in fk_cols
                  and not c.lower().endswith("_id")
                  and not c.lower() == "id"]
        if usable:
            return usable[0]
        non_pk = [c for c in texts if c not in pks]
        if non_pk:
            return non_pk[0]
        return texts[0] if texts else None

    def find_all_dimensions(self, table: str):
        """Return all usable text dimension columns."""
        texts = self.get_text_cols(table)
        pks = set(self.get_pk(table))
        fk_cols = set(fk[0] for fk in self.get_fks(table))
        return [c for c in texts
                if c not in pks and c not in fk_cols
                and not c.lower().endswith("_id")
                and not c.lower() == "id"]

    def find_best_datetime(self, table: str):
        """Pick the most analytically useful datetime column."""
        dts = self.get_datetime_cols(table)
        if dts:
            # No hardcoded name preferences — just return the first datetime column
            return dts[0]
        # Fallback for sources with weak typing (CSV dates arrive as TEXT):
        # a text column whose NAME is date-like is usable with strftime/date_trunc.
        date_hints = ("date", "time", "day", "month", "year", "created",
                      "updated", "timestamp", "period")
        for col in self.get_text_cols(table):
            low = col.lower()
            if any(h in low for h in date_hints):
                return col
        return None

    def find_join_path(self, from_table: str, to_table: str) -> list:
        """Find a join path using FK relationships.
        Returns list of (from_table, from_col, to_table, to_col)."""
        if from_table == to_table:
            return []

        for fk_col, ref_table, ref_col in self.get_fks(from_table):
            if ref_table == to_table:
                return [(from_table, fk_col, to_table, ref_col)]

        for fk_col, ref_table, ref_col in self.get_fks(to_table):
            if ref_table == from_table:
                return [(to_table, fk_col, from_table, ref_col)]

        for fk1_col, ref1_table, ref1_col in self.get_fks(from_table):
            for fk2_col, ref2_table, ref2_col in self.get_fks(ref1_table):
                if ref2_table == to_table:
                    return [
                        (from_table, fk1_col, ref1_table, ref1_col),
                        (ref1_table, fk2_col, to_table, ref2_col),
                    ]

        return []

    def build_join_clause(self, joins: list, dialect: str = "postgresql") -> str:
        """Build SQL JOIN clause from a list of join steps."""
        clauses = []
        for from_t, from_c, to_t, to_c in joins:
            clauses.append(
                f'JOIN {_safe_name(to_t, dialect)} ON '
                f'{_safe_name(from_t, dialect)}.{_safe_name(from_c, dialect)} = '
                f'{_safe_name(to_t, dialect)}.{_safe_name(to_c, dialect)}'
            )
        return " ".join(clauses)

    def get_table_row_count(self, table: str) -> bool:
        """Check if table has a row_count in metadata."""
        info = self.tables.get(table, {})
        return info.get("row_count", 0) if "row_count" in info else None
