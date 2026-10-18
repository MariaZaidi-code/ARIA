# AGENTS.md — ARIA

Repo-specific guidance for automated agents and contributors.

## Verify commands (run before considering work done)

Backend:

```bash
python -c "import app; print('routers:', len(app.app.routes))"   # import/wiring gate
python -m pytest tests/ -q \
  --ignore=tests/e2e \
  --ignore=tests/test_e2e_full.py \
  --ignore=tests/test_walmart_e2e.py \
  --ignore=tests/test_adventureworks_integration.py
```

Frontend (from `aria-frontend/`):

```bash
npm ci
npm run lint
npm run typecheck
npm run build
npm run audit:high
```

Full E2E (Playwright, needs the backend serving the built `dist/` on :8000):

```bash
cd aria-frontend && npx playwright test
```

## Conventions

- Python 3.11; FastAPI + SQLAlchemy + Pydantic v2.
- Request models: use `model_config = ConfigDict(extra="allow")` (do **not** use
  the legacy `class Config:` — deprecated in Pydantic v2, removed in v3).
- SQL: never interpolate raw user/schema identifiers. Validate with
  `core.semantic.is_valid_identifier` and quote via `_quote` / `_safe_name`;
  all execution goes through `core.validation.enforce_readonly_guards`.
- SQLAlchemy engines: build with a bounded `connect_timeout` for server
  backends and always `dispose()` (see `api/data_routes._make_engine`).
- Errors returned to clients must pass through `core.errors.sanitize_error`.
- Secrets: never log or return plaintext; at rest they are DPAPI-encrypted
  (`core/secret_box.py`).

## Notes

- `work/` and `reports/` are local scratch/validation outputs (gitignored).
- Optional export dependencies: `openpyxl` (XLSX) and `python-pptx` (PPTX);
  when absent the export route returns 501 with an actionable message.