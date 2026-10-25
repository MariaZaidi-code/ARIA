"""Lexical/name helpers (database-independent relational principles, PART 17).

These implement general naming-convention reasoning: identifier
normalization, tokenization, singular/plural handling and "is this an
identifier-flavored name" detection. They contain no database-specific lists
(AdventureWorks/Northwind/etc.) — only general English convention rules.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Set

# Tokens that signal "this word is about identifiers/keys", never content words.
ID_TOKENS = {"id", "no", "num", "number", "code", "key", "fk", "ref", "uuid", "sk", "nk"}

# Suffixes that conventionally mark a column as referencing another entity.
# General relational conventions (PART 4 / PART 17): "_id" plus the common
# `_ref` / `_key` / `_no` / `_num` families used across arbitrary schemas. The
# `_code` family is deliberately excluded: it is ambiguous (status/country/
# currency codes collide with PKs by coincidence) and is handled by the
# code-like evidence signal + policy veto instead.
REF_FLAVORED_SUFFIXES = ("_id", "_by", "_to", "_from", "_via", "_for", "_at",
                         "_with", "_against", "_on", "_of", "_type",
                         "_ref", "_key", "_no", "_num", "_nbr",
                         "_uuid", "_sk", "_nk")


def _strip_outer_quotes(value: str) -> str:
    """Strip surrounding quotes/brackets/whitespace (generic, dialect-agnostic)."""
    s = str(value or "").strip()
    while len(s) >= 2 and ((s[0] == '"' and s[-1] == '"')
                           or (s[0] == "'" and s[-1] == "'")
                           or (s[0] == "`" and s[-1] == "`")
                           or (s[0] == "[" and s[-1] == "]")):
        s = s[1:-1].strip()
    return s


def canonical_identifier(value: str) -> str:
    """Lower + quote-stripped match key for case-insensitive identifiers."""
    return _strip_outer_quotes(value).lower()


def bare_identifier(value: str) -> str:
    """Bare last dot-segment, canonicalized (multi-schema aware)."""
    segs = [s for s in str(value or "").split(".") if s.strip()]
    last = segs[-1] if segs else str(value or "")
    return canonical_identifier(last)


def fold_identifier_tokens(value: str) -> List[str]:
    """Lowercase word tokens folding CamelCase + separators + quotes.

    "SalesOrderHeader" -> ["sales", "order", "header"]; '"TotalDue"' ->
    ["total", "due"]. Generic English-convention folding, no name lists.
    """
    s = _strip_outer_quotes(value)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in re.split(r"[^a-zA-Z0-9]+", s.lower()) if w]


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", canonical_identifier(value))


# Words whose singular and plural are spelled the same (or that only look
# plural). General English, not schema names.
_INVARIANT_WORDS = {"news", "series", "species", "gas", "bias", "alias",
                    "atlas", "canvas", "data", "media", "chassis"}
_IRREGULAR_PLURALS = {"person": "people", "child": "children", "man": "men",
                      "woman": "women"}
_IRREGULAR_SINGULARS = {v: k for k, v in _IRREGULAR_PLURALS.items()}


def singularize(name: str) -> str:
    """Best-effort singular of an English identifier.

    'categories' -> 'category', 'addresses' -> 'address', 'boxes' -> 'box',
    'statuses' -> 'status', 'analyses' -> 'analysis'; already-singular words
    ending in -us / -is / -ss ('status', 'analysis', 'address') and
    invariant words ('series', 'news') are left alone.
    """
    low = name.lower()
    tail = re.split(r"[^a-z0-9]+", low)[-1]
    if tail in _INVARIANT_WORDS:
        return name
    if tail in _IRREGULAR_SINGULARS:
        return name[:len(name) - len(tail)] + _IRREGULAR_SINGULARS[tail]
    if low.endswith("ies") and len(name) > 4:
        return name[:-3] + "y"
    if low.endswith("yses") and len(name) > 5:
        return name[:-2] + "is"
    if low.endswith(("sses", "xes", "ches", "shes", "zzes")) and len(name) > 4:
        return name[:-2]
    if low.endswith("uses") and len(name) > 4 and low[-5] not in "aeiou":
        return name[:-2]
    if low.endswith(("ss", "us", "is")):
        return name
    if low.endswith("s") and len(name) > 2:
        return name[:-1]
    return name


def pluralize(word: str) -> str:
    """Best-effort English plural of a single word ('category' ->
    'categories', 'status' -> 'statuses', 'analysis' -> 'analyses')."""
    w = str(word or "")
    low = w.lower()
    if not w or low in _INVARIANT_WORDS:
        return w
    if low in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[low]
    if low.endswith("is") and len(w) > 3:
        return w[:-2] + "es"
    if low.endswith("y") and len(w) > 1 and low[-2] not in "aeiou":
        return w[:-1] + "ies"
    if low.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    return w + "s"


# Common data-shorthand tokens -> plain English (generic naming conventions,
# not business or schema names). Used for user-facing labels and so goal
# words match abbreviated columns ("amount" <-> "amt").
ABBREVIATIONS = {
    "amt": "amount", "amnt": "amount", "qty": "quantity", "qnty": "quantity",
    "cnt": "count", "avg": "average", "tot": "total", "val": "value",
    "num": "number", "nbr": "number", "pct": "percent", "perc": "percent",
    "desc": "description", "cat": "category", "yr": "year", "yrs": "years",
    "mth": "month", "dt": "date", "ts": "timestamp", "txn": "transaction",
    "trx": "transaction", "txns": "transactions", "cust": "customer",
    "nm": "name", "cd": "code", "addr": "address", "acct": "account",
    "mthd": "method", "pmt": "payment", "pymt": "payment", "prod": "product",
    "dept": "department", "emp": "employee", "mgr": "manager", "ord": "order",
    "qtr": "quarter", "wk": "week", "disc": "discount", "rev": "revenue",
    "prc": "price", "bal": "balance", "loc": "location", "curr": "currency",
    "ccy": "currency", "freq": "frequency", "uom": "unit of measure",
    "src": "source", "dest": "destination", "ref": "reference",
}


def expand_abbreviation(token: str) -> str:
    """Plain-English word for a shorthand token ('amt' -> 'amount');
    unknown tokens are returned lowercased and unchanged."""
    low = str(token or "").lower()
    return ABBREVIATIONS.get(low, low)


def identifier_words(name: str) -> List[str]:
    """Lowercase words of an identifier with shorthand expanded.

    Splits snake_case, kebab-case, spaces and CamelCase, and drops any
    schema/table qualifier: 'sales.SalesOrderHeader' -> ['sales', 'order',
    'header']; 'pay_mthd' -> ['payment', 'method']. Multi-word expansions
    ('uom') are split into their words.
    """
    bare = _strip_outer_quotes(str(name or "")).split(".")[-1]
    out: List[str] = []
    for tok in tokenize_words(bare):
        out.extend(expand_abbreviation(tok).split())
    return out


def humanize_identifier(name: str) -> str:
    """Plain-English phrase for an identifier: 'TotalDue' -> 'total due',
    'txn_dt' -> 'transaction date', 'cust_nm' -> 'customer name'.
    Falls back to the raw text when it has no word characters."""
    words = identifier_words(name)
    return " ".join(words) if words else str(name or "").strip()


def is_ref_flavored(name) -> bool:
    """Expanded FK-name signal: catches _id, _by, _to, _from, _via, _for, etc."""
    if not isinstance(name, str):
        return False
    low = name.lower()
    if low == "id":
        return True
    # Split camelCase first so MediaTypeId/SupportRepID behave like
    # snake_case (separator-less "valid"/"grid" still correctly rejected).
    low = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name)).lower()
    for suffix in REF_FLAVORED_SUFFIXES:
        if low.endswith(suffix):
            return True
    # NOTE: bare endswith("id") was removed — it misclassified ordinary
    # words ("valid", "grid", "liquid"). Separator-less forms are only
    # accepted via tokenize_words() ID_TOKENS by callers that need them.
    return False


def tokenize_words(name: str) -> List[str]:
    """Split an identifier into lowercase word tokens (snake_case, camelCase...).

    "MediaTypeId" -> ["media", "type", "id"]; "support_rep_id" -> ["support", "rep", "id"].
    This is what lets name matching work on ANY naming convention, not just X_id.
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name))
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in re.split(r"[^a-zA-Z0-9]+", s.lower()) if w]


def table_name_forms(base: str) -> Set[str]:
    """Singular/plural forms a table name could take for `base`."""
    base = singularize(base)
    forms = {base, base + "s", base + "es"}
    if base.endswith("y") and len(base) > 1:
        forms.add(base[:-1] + "ies")
    forms.add(singularize(base))
    return forms


def table_name_candidates(col_name: str, tables: Iterable[str]) -> List[str]:
    """For 'X_id' (or 'Xid'), return tables whose name (singular or plural) is X.

    Generalized token match: any naming style, not just X_id (PART 4 lexical
    signal). A bare trailing "id" with no separator (`storeid`, `personid`) is
    stripped so it matches the same way `store_id` does. Pure candidate
    generation - it never accepts a relationship.
    """
    base = col_name[:-3].lower() if col_name.endswith("_id") else col_name.lower()
    forms = table_name_forms(base)
    names = [t for t in tables if str(t).lower() in forms]
    if not names:
        strip_id = base[:-2] if base.endswith("id") and len(base) > 3 else base
        col_tokens = {singularize(tok) for tok in tokenize_words(strip_id)
                      if tok not in ID_TOKENS}
        if col_tokens:
            for t in tables:
                # Table-name tokens only: the schema prefix is context, not a
                # name-match signal (PART 18), so `personid` must not match a
                # table merely because its schema is named "person".
                t_part = str(t).rsplit(".", 1)[-1]
                t_tokens = {singularize(tok) for tok in tokenize_words(t_part)}
                if col_tokens <= t_tokens:
                    names.append(t)
    return sorted(set(names))


def most_specific_table(base_tokens: Set[str], tables: Iterable[str]) -> str | None:
    """Shortest table whose name tokens intersect `base_tokens` (name specificity).

    `orders` outranks `olist_order_items_dataset` because it is a shorter,
    more specific name for the token `order`.
    """
    best = None
    for t in tables:
        name_part = str(t).rsplit(".", 1)[-1]
        table_tokens = {singularize(tok) for tok in tokenize_words(name_part)}
        if not table_tokens:
            continue
        if table_tokens & base_tokens:
            if best is None or len(str(t)) < len(str(best)):
                best = t
    return best


def is_reference_to_other_table(col_name: str, table_name: str, tables: Iterable[str]) -> bool:
    """True when `col_name` (X_id style) names ANOTHER table (X/Xs/Xes/Xies).

    A column like `order_id` in a table that also has an `orders` table is
    almost certainly a foreign key, NOT the table's own primary key.
    """
    base = col_name[:-3].lower() if col_name.endswith("_id") else col_name.lower()
    if not base or base in ID_TOKENS:
        return False
    forms = table_name_forms(base)

    def _matches(t) -> bool:
        if normalize_identifier(t) in forms:
            return True
        return any(singularize(tok) in forms for tok in tokenize_words(t))

    best = None
    for t in tables:
        if not _matches(t):
            continue
        if best is None or len(str(t)) < len(str(best)):
            best = t
    return best is not None and best != table_name


def is_code_column(col_name: str) -> bool:
    """True for categorical label/code columns that collide with PKs by chance.

    `status`, `country_code`, `category`, `year`, `department` etc. often share
    values with primary keys (1..n) and must be penalized heavily as FK
    candidates — they are almost never real references.

    NOTE: this is a general *semantic* signal (code-like words). The word list
    will be converted into a general evidence signal in Phase E.
    """
    low = col_name.lower()
    base = low[:-3] if low.endswith("_id") else low
    tokens = set(tokenize_words(base))
    code_words = {
        "status", "category", "subcategory", "country", "city", "state",
        "region", "year", "month", "day", "week", "department", "gender",
        "channel", "segment", "tier", "type", "flag", "currency", "language",
        "color", "size", "brand", "name", "label", "grade", "level",
    }
    return any(t in code_words for t in tokens)