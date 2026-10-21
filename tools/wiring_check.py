"""End-to-end wiring check for ARIA (audit plan 4.3 verification matrix).

Loads one dataset into a throwaway copy of the app and asks the same
questions through every answering surface, then checks:

  * numbers   - each answer's value matches the spec's expected value
                (Analytics /api/ask, Ask ARIA /api/copilot, Dashboard cards);
  * hygiene   - no NaN / None / null / undefined / Infinity, no SQL or
                formula fragments, no raw column or table identifiers in any
                user-facing text (answers, suggestions, autocomplete, cards);
  * wiring    - every endpoint answers 200 with a usable payload.

Safe by construction: the code is copied to a temp folder with an EMPTY
data/ directory, so real sessions, uploads and accounts are never read or
written. The temp copy is deleted afterwards.

Spec file (JSON):
    {
      "dataset": "work/datasets/dataset_C_messy_txns.csv",   # CSV, or
      "postgres": {"host": "localhost", "port": 5432, "db": "aria_test",
                   "user": "postgres", "password_env": "ARIA_CHECK_PG_PASSWORD"},
      "questions": [{"q": "What is the total amt?", "expect": 1071222, "tol": 0.5}],
      "cards": [{"label": "Total Amount", "expect": 1071222}],
      "autocomplete": ["what is", "which"]
    }

Usage (PowerShell):
    python tools/wiring_check.py work/datasets/check_C.json
    python tools/wiring_check.py work/datasets/check_A.json --json report.json

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
_IGNORE = ("venv", "node_modules", "data", "artifacts", ".git", "work", "dist",
           "__pycache__", ".pytest_cache", "reports")

_BAD_TOKENS = re.compile(r"\b(NaN|None|null|undefined|Infinity|-Infinity)\b")
_SQL_BITS = re.compile(r"\b(SELECT|FROM\s+\w+\s+WHERE|GROUP BY|ORDER BY|COALESCE|CAST)\b|"
                       r"\b(SUM|AVG|COUNT|MIN|MAX)\s*\(|[=<>]{1,2}\s*\d|\w\.\w+_\w")


def _isolated_rerun() -> int:
    """Re-run this script inside a temp copy of the repo (empty data/)."""
    tmp = Path(tempfile.mkdtemp(prefix="aria_wiring_"))
    dst = tmp / "app"
    try:
        shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns(*_IGNORE))
        (dst / "tools").mkdir(exist_ok=True)
        shutil.copy2(__file__, dst / "tools" / "wiring_check.py")
        args = [str(Path(a).resolve()) if Path(a).is_file() else a for a in sys.argv[1:]]
        env = dict(os.environ, ARIA_WIRING_ISOLATED="1", ARIA_WIRING_SRC=str(SRC),
                   PYTHONIOENCODING="utf-8", ARIA_COOKIE_SECURE="0", ARIA_ENV="dev")
        return subprocess.call([sys.executable, str(dst / "tools" / "wiring_check.py"), *args],
                               cwd=str(dst), env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _numbers(text: str) -> list[float]:
    out = []
    for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?\s*[KMB]?", str(text or "")):
        tok = m.group(0).replace(",", "").strip()
        mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(tok[-1:], 1)
        try:
            out.append(float(tok.rstrip("KMB").strip()) * mult)
        except ValueError:
            continue
    return out


def _value_matches(payload: dict, expect: float, tol: float) -> tuple[bool, str]:
    """True when the expected value appears in the returned rows (exact) or
    in the answer text (exact or its rounded short form)."""
    for row in (payload.get("data") or [])[:50]:
        if isinstance(row, dict):
            for v in row.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v - expect) <= tol:
                    return True, f"row value {v}"
    answer = str(payload.get("answer") or "")
    for n in _numbers(answer):
        rel = abs(n - expect) / max(abs(expect), 1.0)
        if abs(n - expect) <= tol or rel <= 0.051:
            return True, f"answer says {n:g}"
    return False, f"answer: {answer[:120]!r}"


class Report:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, surface: str, check: str, ok: bool, detail: str = ""):
        self.rows.append({"surface": surface, "check": check, "ok": bool(ok), "detail": detail})

    def hygiene(self, surface: str, check: str, text: str, raw_names: set[str]):
        text = str(text or "")
        problems = []
        if _BAD_TOKENS.search(text):
            problems.append(f"bad token {_BAD_TOKENS.search(text).group(0)!r}")
        if _SQL_BITS.search(text):
            problems.append(f"SQL/formula {_SQL_BITS.search(text).group(0)!r}")
        for raw in raw_names:
            if re.search(rf"(?<![\w]){re.escape(raw)}(?![\w])", text):
                problems.append(f"raw identifier {raw!r}")
                break
        self.add(surface, f"plain words: {check}", not problems,
                 "; ".join(problems) or text[:80])

    def print(self):
        width = max((len(r["surface"]) for r in self.rows), default=8)
        for r in self.rows:
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"{mark}  {r['surface']:<{width}}  {r['check']}  -- {r['detail']}")
        fails = sum(not r["ok"] for r in self.rows)
        print(f"\n{len(self.rows) - fails} passed, {fails} failed")
        return fails


def _run(spec_path: str, json_out: str | None) -> int:
    sys.path.insert(0, str(Path.cwd()))
    from fastapi.testclient import TestClient
    import app as app_module

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    report = Report()
    c = TestClient(app_module.app, raise_server_exceptions=False)
    r = c.post("/api/auth/register", json={"username": f"wiring{int(time.time()) % 10**8}",
                                           "password": "Secret123!"})
    report.add("auth", "register", r.status_code == 200, str(r.status_code))

    # ---- connect ---------------------------------------------------------
    if spec.get("dataset"):
        ds = Path(spec["dataset"])
        if not ds.is_absolute():
            ds = Path(os.environ.get("ARIA_WIRING_SRC", ".")) / ds
        with open(ds, "rb") as fh:
            r = c.post("/api/connect_file", files={"file": (ds.name, fh, "text/csv")})
    else:
        pg = dict(spec["postgres"])
        pg["password"] = os.environ.get(pg.pop("password_env", ""), pg.get("password", ""))
        r = c.post("/api/connect/postgresql", json={"source_type": "relational", **pg})
    report.add("connect", "dataset loads", r.status_code == 200, r.text[:120] if r.status_code != 200 else "ok")
    if r.status_code != 200:
        return report.print()

    raw_names: set[str] = set()
    schema = c.get("/api/schema")
    try:
        tables = (schema.json().get("tables") or schema.json().get("schema", {}).get("tables") or {})
        for t, info in (tables.items() if isinstance(tables, dict) else []):
            raw_names.add(str(t).split(".")[-1])
            cols = info.get("columns") or {}
            names = cols if isinstance(cols, dict) else [x.get("column", "") for x in cols if isinstance(x, dict)]
            raw_names.update(str(n) for n in names)
    except Exception:
        pass
    # Only identifiers that do not read as plain words count as leaks.
    raw_names = {n for n in raw_names if "_" in n or re.search(r"[a-z][A-Z]", n)}

    # ---- questions on every answering surface ----------------------------
    for item in spec.get("questions", []):
        q, expect, tol = item["q"], item.get("expect"), float(item.get("tol", 0.5))
        for surface, path, body in (("analytics", "/api/ask", {"goal": q}),
                                    ("ask-aria", "/api/copilot", {"question": q})):
            t0 = time.time()
            r = c.post(path, json=body)
            secs = time.time() - t0
            payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code == 200 and payload.get("ok", True) is not False
            report.add(surface, f"answers {q!r}", ok, f"{r.status_code} in {secs:.1f}s")
            if not ok:
                continue
            if expect is not None:
                good, why = _value_matches(payload, float(expect), tol)
                report.add(surface, f"correct value for {q!r} (expect {expect:g})", good, why)
            report.hygiene(surface, f"answer to {q!r}", payload.get("answer", ""), raw_names)
            for s in (payload.get("suggested_questions") or [])[:8]:
                report.hygiene(surface, "follow-up suggestion", s, raw_names)

    # ---- dashboard cards ---------------------------------------------------
    r = c.get("/api/dashboard/config")
    cfg = (r.json() or {}).get("config", {}) if r.status_code == 200 else {}
    metrics = cfg.get("metrics") or []
    report.add("dashboard", "cards load", r.status_code == 200 and bool(metrics), f"{len(metrics)} cards")
    for m in metrics:
        report.hygiene("dashboard", f"card {m.get('label')!r}", f"{m.get('label')} {m.get('value')}", raw_names)
    for card in spec.get("cards", []):
        hit = next((m for m in metrics if str(m.get("label", "")).lower() == card["label"].lower()), None)
        if not hit:
            report.add("dashboard", f"card {card['label']!r} present", False, "missing")
            continue
        raw = hit.get("rawValue")
        good = isinstance(raw, (int, float)) and abs(float(raw) - float(card["expect"])) <= float(card.get("tol", 0.5))
        report.add("dashboard", f"card {card['label']!r} = {card['expect']:g}", good, f"rawValue {raw}, shown {hit.get('value')!r}")

    # ---- starter suggestions + autocomplete --------------------------------
    r = c.post("/api/suggestions", json={"limit": 8})
    sugg = (r.json() or {}).get("suggestions") or []
    report.add("suggestions", "4-8 starter questions", 4 <= len(sugg) <= 8, f"{len(sugg)} items")
    for s in sugg:
        report.hygiene("suggestions", "starter", s, raw_names)
    for partial in spec.get("autocomplete", []):
        r = c.post("/api/autocomplete", json={"partial": partial, "limit": 8})
        items = [s.get("text", "") for s in (r.json() or {}).get("suggestions", [])]
        report.add("autocomplete", f"{partial!r} returns suggestions", bool(items), f"{len(items)} items")
        # Continues the typed words (shorthand counts as its meaning:
        # 'total amt' is continued by 'What is the total amount?').
        try:
            from schema_engine.lexical import expand_abbreviation
        except ImportError:  # older checkouts: minimal shorthand map
            def expand_abbreviation(w, _m={"amt": "amount", "qty": "quantity",
                                           "txn": "transaction", "avg": "average"}):
                return _m.get(w, w)
        typed = [expand_abbreviation(w) for w in re.findall(r"[a-z0-9]+", partial.lower())]
        cont = [t for t in items
                if t.lower().startswith(partial.lower())
                or all(re.search(rf"\b{re.escape(w)}", t.lower()) for w in typed)]
        report.add("autocomplete", f"{partial!r} continues the typed text", bool(cont),
                   cont[0] if cont else (items[0] if items else "none"))
        for t in items:
            report.hygiene("autocomplete", f"{partial!r}", t, raw_names)

    fails = report.print()
    if json_out:
        Path(json_out).write_text(json.dumps(report.rows, indent=2), encoding="utf-8")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    if os.environ.get("ARIA_WIRING_ISOLATED") != "1":
        return _isolated_rerun()
    json_out = None
    if "--json" in sys.argv:
        json_out = sys.argv[sys.argv.index("--json") + 1]
        if not Path(json_out).is_absolute():
            json_out = str(Path(os.environ.get("ARIA_WIRING_SRC", ".")) / json_out)
    return _run(sys.argv[1], json_out)


if __name__ == "__main__":
    sys.exit(main())
