# ARIA Codebase — Comprehensive Analysis Report

**Generated:** 2026-10-25 · **Branch:** `maria` · **Working tree:** dirty (uncommitted fixes in progress)
**Scope:** Full per-file audit of 310 Python + 32 TSX + 9 TS + 8 JS/JSX files across backend, frontend, tests, and tooling.
**Method:** Three parallel subagent audits (backend core/infra, backend AI pipeline, backend API, frontend) + prior targeted audits of document module and reingest scheduler. Every finding below references a concrete `file:line` and was verified against the actual code (not speculation).

---

## 1. Project Overview

**ARIA** ("AI Business Analytics & Intelligence Platform") — a full-stack application that connects PostgreSQL/MySQL/CSV/PDF sources and answers natural-language business questions with validated SQL execution, evidence, visualizations, insights, forecasts, prescriptions, and hypothesis tests.

- **Purpose**: NL → validated analytics, with a fail-closed "honesty" design (no fabricated answers, `valid:false` on missing evidence, abstention on weak grounding).
- **Backend:** Python 3.11, FastAPI, SQLAlchemy, Pydantic v2, SQLite local stores, Postgres+PGVector + DeepSeek hosted LLM for RAG.
- **Frontend:** React 19 + Vite, hash-routed SPA (`#/page`).
- **Tests:** 192 pytest files; Playwright E2E; CI (GitHub Actions) with coverage gate ≥20%, gitleaks, frontend lint/typecheck/build, E2E.
- **Scale:** ~106k LOC backend; 285+ Python files; 28 FastAPI routers; 196 API routes.

### Top-level layout
```
aria/
├── app.py                      FastAPI entry (28 routers, lifespan, SPA fallback)
├── auth.py, llm_provider.py, csv_handler.py, csv_orchestrator.py, full_audit.py
├── core/                       19 foundational modules
├── api/                        24 routers (196 routes)
├── goal_agent/, schema_agent/, schema_engine/, insight_agent/, insight_rag/, insight_extensions/
├── prediction/, prescription_engine/, hypothesis_engine/, copilot/
├── document_processor/         legacy FAISS store (partially superseded)
├── services/                   business_360, insights, intelligence, kpi, workspace, reingest_scheduler
├── verification/, reporting/, memory/, models/, tools/, _archive/, work/, reports/
├── aria-frontend/              React 19 + Vite
└── tests/                      192 test files
```

---

## 2. Backend — Core & Infrastructure

**Audited:** `app.py`, `core/*`, root scripts, `models/`, `memory/`, `tools/`, `verification/`, `reporting/`, `services/`.

### 2.1 File status summary

| Directory | Files | Wired-in? | Health |
|---|---:|---|---|
| Root (`app.py`, `auth.py`, `llm_provider.py`, …) | 6 | Yes (app.py entry; auth.py & llm_provider.py core deps) | Good; `csv_handler.py`/`csv_orchestrator.py` are 4-line compat shims; `full_audit.py` is a standalone manual script (not wired) |
| `core/` | 19 | All wired via lazy imports | Good — compile clean, only cosmetic unused locals |
| `models/` | 0 Python (adapter artifacts only) | Inert data (Mistral LoRA) | N/A |
| `memory/` | 0 Python (markdown notes) | Documentation only | N/A |
| `tools/` | 2 (`wiring_check.py`, `cleanup_dev.py`) | Standalone CLI tools | Good |
| `verification/` | 1 (`agent.py`) | Wired via `verification_routes.py` | Good |
| `reporting/` | 3 (`agent.py`, `digests.py`, `monitors.py`) | Wired via intelligence/workspace routes | Good |
| `services/` | 9 (incl. reingest_scheduler) | All wired via API routes | Good |

### 2.2 Issues (core/infra)

| # | File:line | Sev | Issue |
|---|---|---|---|
| 1 | `auth.py:629-633` | MEDIUM | `get_admin_overview` re-raises after `SELECT 1` failure instead of returning a degraded payload → admin endpoint returns 500. |
| 2 | `services/insights_service.py:11-16` | LOW | Unused imports (`sqlite3`, `statistics`, `time`, `DB_ERRORS`, `PURE_ERRORS`, `get_request_id`, `log_and_sanitize`). |
| 3 | `services/insights_service.py:701-718,772-773` | LOW | f-strings with no placeholders. |
| 4 | `services/intelligence_service.py:18,22,24,25,33,35` | LOW | Unused imports (`time`, `typing.*`, `numpy`, `pandas`, `is_dimension_like`, `is_technical_role`). |
| 5 | `services/intelligence_service.py:1082,2678,2810` | LOW | Unused `sqlalchemy.create_engine` imports. |
| 6 | `services/intelligence_service.py:1120` | LOW | Unused local `time_label`. |
| 7 | `services/intelligence_service.py:2354,3073` | LOW | Unused `exc` in exception handlers. |
| 8 | `services/intelligence_service.py:3035` | LOW | f-string without placeholders. |
| 9 | `services/kpi_service.py:10,15-19,21,24,26` | LOW | Many unused imports (`json`, `sqlite3`, `types`, `timedelta`, `Path`, `quote_plus`, `create_engine`, `humanize`, `kpi_label`, `get_request_id`, `log_and_sanitize`). |
| 10 | `services/workspace_service.py:930` | LOW | Unused local `saved`. |
| 11 | `llm_provider.py:22` | LOW | Unused import `urllib.parse.quote_plus`. |
| 12 | `llm_provider.py:42-43` | LOW | Library module calls `logging.basicConfig` at import when no handlers (can hijack app logging). |
| 13 | `core/config.py:797` | LOW | Unused local `exc`. |
| 14 | `core/schema_intel.py:283` | LOW | Unused local `low`. |
| 15 | `core/semantic.py:145` | LOW | Unused local `name`. |
| 16 | `tools/cleanup_dev.py:27` | LOW | Unused import `os`. |
| 17 | `full_audit.py` | LOW | Hardcoded absolute path; manual script, not wired into app/CI. |
| 18 | `services/csv_llm_service.py` | LOW | Compat alias with no production import sites (only tests) — legacy shim of uncertain liveness. |
| 19 | `verification/__init__.py:3` | LOW | Re-exports only `verify_dashboard` though `agent.py` also defines `verify_ask`/`verify_forecast`/`verify_prescription`. |

### 2.3 Dead code (core/infra)
- `services/csv_llm_service.py` — compat shim, no non-test importers.
- `full_audit.py` — standalone manual audit script, not referenced.
- `tools/cleanup_dev.py`, `tools/wiring_check.py` — standalone CLI tools, not wired into runtime.
- `models/aria-story-mistral-7b-lora/*` — adapter artifacts only (no Python).
- `memory/*.md` — documentation only.
- `_archive/` helper scripts — legacy.
- Unused imports/locals listed above.

### 2.4 Verdict (core/infra)
**GOOD / production-grade posture.** Import and compile gates pass; no undefined-name (F821) errors; security layers (PBKDF2 600k, DPAPI, SSRF validation, readonly SQL guards, rate limits, CSP, trusted hosts, canonical error shapes) present and wired. Issues are cosmetic plus one medium (admin endpoint re-raises on DB probe). No CRITICAL/HIGH defects.

---

## 3. Backend — AI/ML Pipeline

**Audited:** `goal_agent/`, `schema_agent/`, `schema_engine/`, `insight_agent/`, `insight_extensions/`, `insight_rag/`, `prediction/`, `prescription_engine/`, `hypothesis_engine/`, `copilot/`, `verification/`, `core/rl.py`, `api/rl_routes.py`.

### 3.1 Module status

| Module | Purpose | Wired-in? | Health |
|---|---|---|---|
| `goal_agent/` | Goal/SQL analytics agent (intent, schema grounding, SQL gen/repair, execution) | Yes (query/predictive/insights routes) | Healthy; uses `sql`/`suggest` roles |
| `schema_agent/` | DB introspection, PK/FK inference, schema reasoning, snapshots | Yes (connect/kpi/predictive routes) | Healthy; uses `schema` role |
| `schema_engine/` | Lexical helpers + schema models/policy/profiling | Yes (autocomplete/kpi/predictive/query) | Healthy (utility layer) |
| `insight_agent/` | Dashboard/story insights, advanced & industry variants | Yes (insights/rag routes) | Healthy; uses `story`/`suggest`; imports legacy `prescription_agent` |
| `insight_extensions/` (top-level) | Deprecated shim re-exporting `insight_agent.extensions` | No external callers (dead shim) | Dead code |
| `insight_agent/extensions/` | DecisionIntelligence used by IndustryInsightAgent | Indirect (via industry) | Healthy |
| `insight_rag/` | Document RAG pipeline (routing, retrieval, grounding, answer stability) | Yes (rag/document/hypothesis routes) | Healthy; RAG roles + per-query budget |
| `prediction/` | Time-series & tabular forecasting | Yes (predictive routes) | Healthy |
| `prescription_engine/` | Recommendations, scenarios, alerts | Yes (prescription routes) | Healthy (no LLM) |
| `hypothesis_engine/` | Statistical hypothesis testing/investigation | Yes (hypothesis routes) | Healthy; uses `story` role |
| `copilot/` | Schema-aware NL copilot (retrieval, SQL, answers) | Yes (copilot routes) | Healthy; uses `sql`/`story` |
| `verification/agent.py` | Dashboard/ask/forecast/prescription verification | Yes | Healthy |
| `core/rl.py` + `api/rl_routes.py` | RL telemetry/feedback/ranking | Yes (rl routes) | Healthy |

### 3.2 Issues (AI pipeline)

| # | File:line | Sev | Issue |
|---|---|---|---|
| 1 | `tests/test_rag_cloud_provider_stability.py:45` | LOW | Failing assertion `cloud["models"]["sql"].startswith("deepseek-")` because `.env` sets `DEEPSEEK_MODEL=openai/gpt-4o-mini` (OpenRouter config) — environment-driven, not a code defect. |
| 2 | `insight_agent/agent.py:33` | MEDIUM | Imports legacy `prescription_agent` wrapper instead of `prescription_engine` — couples a live agent to a compatibility shim. |
| 3 | Top-level `goal_agent.py`, `schema_agent.py`, `insight_agent.py`, `prescription_agent.py` | MEDIUM | Shadowed monolithic duplicates of the canonical packages; unreachable as modules (package wins) but still present/maintained → drift risk. |
| 4 | `insight_extensions/decision_intelligence.py` | LOW | Deprecated shim with no external callers — dead code. |
| 5 | `_archive/` scripts | LOW | Legacy audit/test helpers not part of runtime; clutter. |

No missing imports, invalid LLM role strings, or retry-loop defects were found in the audited target modules (ruff F-check clean; all submodules import successfully). Full test suite: 949 passed, 1 failed (environment-driven `.env` model-name mismatch).

### 3.3 Dead code (AI pipeline)
- `insight_extensions/` top-level package (self-referential shim only).
- Top-level monoliths: `goal_agent.py`, `schema_agent.py`, `insight_agent.py`, `prescription_agent.py` (shadowed by same-named packages).
- `_archive/` helper scripts; `work/`, `reports/` scratch outputs (gitignored).

### 3.4 Verdict (AI pipeline)
**HEALTHY / PASS.** Import and wiring gates pass; no runtime-breaking issues. Main concerns are legacy duplicate/shim code and one environment-sensitive test assertion.

---

## 4. Backend — API Layer (excluding document_routes.py / insight_rag_routes.py)

**Audited:** 22 routers in `api/` (161 endpoints among 196 total). Import/wiring gate passes (`import app` succeeds with 196 API routes total).

### 4.1 Per-router status

| Router | Endpoints | Status |
|---|---:|---|
| `api/__init__.py` | 0 | Empty module; routers imported directly in `app.py`. OK |
| `auth_routes.py` | 11 | Auth/register/login/logout/me/history/admin. OK |
| `autocomplete_routes.py` | 4 | Autocomplete + conversation store/resolve. OK |
| `connect_routes.py` | 14 | Connect DB/file/PDF/provider; **duplicate `session_status` name** |
| `copilot_routes.py` | 2 | `/api/copilot` suggestions + ask. OK |
| `data_routes.py` | 8 | Connection/summary/preview/quality/overrides. OK |
| `export_routes.py` | 1 | `/api/export/story`; optional deps return 501. OK |
| `feedback_routes.py` | 6 | Feedback/ratings/preferences. OK |
| `hypothesis_investigation_routes.py` | 1 | Enriched investigation. OK |
| `hypothesis_routes.py` | 7 | Hypothesis investigate/analyze/parse. OK |
| `insights_routes.py` | 6 | Insights list/saved/save/ask/detail. OK |
| `integrations_routes.py` | 1 | Slack command (token-resolved auth, no FastAPI Depends — OK by design) |
| `intelligence_routes.py` | 36 | Explore/hypotheses/goals/what-if/reports/digests. **Stacked GET/POST `/hypotheses`** |
| `kpi_routes.py` | 6 | Dashboard KPIs/summary/config/chart recommend. OK |
| `predictive_routes.py` | 4 | Eligibility/scenario/forecast + prescription generate. OK |
| `prescription_routes.py` | 11 | Context/analyze/scenario/save/saved/levers/presets/alerts. OK |
| `query_routes.py` | 6 | Suggestions/csv conversation/ask/insight. OK |
| `rl_routes.py` | 5 | RL events/feedback/status/rank. OK |
| `schema_routes.py` | 4 | Extract schema + get schema. OK |
| `settings_routes.py` | 5 | Providers/models/status/general settings. OK |
| `verification_routes.py` | 4 | Verify dashboard/ask/forecast/prescription. OK |
| `workspace_routes.py` | 19 | Monitors/targets/glossary/notifications/webhooks/integrations. OK |

### 4.2 Issues (API layer)

| # | File:line | Sev | Issue |
|---|---|---|---|
| 1 | `connect_routes.py:30` | MEDIUM | Two functions named `session_status` (lines 30 and 1349); later definition shadows the first in module namespace. |
| 2 | `intelligence_routes.py:271` | LOW | GET and POST `/hypotheses` stacked on one function via two decorators; relies on runtime `request.method` branching. |
| 3–18 | Various request-model files | MEDIUM | Most request models lack `model_config = ConfigDict(extra="allow")`: `auth_routes` (AuthRequest, VerificationRequest, ResendVerificationRequest, PageVisitRequest), `autocomplete_routes` (AutocompleteRequest), `connect_routes` (ConnectRequest, ProviderSwitchRequest, DatabaseTestRequest), `copilot_routes` (CopilotRequest), `data_routes` (PreviewRequest, OverrideRequest), `feedback_routes` (InsightRating, SuggestionClick, ChartPreference, GeneralFeedback), `hypothesis_routes` (InvestigateRequest, AnalyzeRequest, ParseRequest, HypothesisRequest), `hypothesis_investigation_routes` (InvestigationRequest), `insights_routes` (SaveInsightRequest, AskInsightRequest), `predictive_routes` (ScenarioRequest, ForecastRequest, PrescriptionRequest), `prescription_routes` (AnalyzeRequest, ScenarioRequest, SaveRequest, SavedUpdateRequest, InactionRequest), `query_routes` (GoalRequest), `rl_routes` (FeedbackEvent, PopupFeedback, RankRequest), `settings_routes` (ProviderConfigRequest, GeneralSettingsRequest). |
| 19 | `schema_routes.py:0` | MEDIUM | No Pydantic request models; endpoints use untyped `Request`/path params only; validation is manual. |
| 20 | `kpi_routes.py:0` | MEDIUM | No Pydantic request models; query params only, no typed validation envelope. |
| 21 | `verification_routes.py:27` | LOW | Endpoints accept `body: dict` instead of a typed Pydantic model; only runtime `_payload_of` unwrapping. |
| 22 | `workspace_routes.py:241` | LOW | `create_webhook` does not enforce HTTPS or SSRF-safe URL validation at route layer. |
| 23 | `integrations_routes.py:137` | MEDIUM | Slack command endpoint has no Slack signature verification; relies solely on workspace token in POST body. |
| 24 | `auth_routes.py:208` | LOW | Register/login/verify/resend endpoints omit `sanitize_error` in some exception paths. |
| 25 | `connect_routes.py:987` | LOW | Connect endpoints return provider/session errors; several paths do not consistently route exceptions through `sanitize_error`. |
| 26 | `connect_routes.py:30` | LOW | Legacy `/session/status` path lacks `/api` prefix (intentional frontend compat, but inconsistent with API surface). |
| 27 | `data_routes.py:476` | LOW | f-string missing placeholders (pyflakes). |
| 28 | `insights_routes.py:1674` | LOW | f-string missing placeholders (pyflakes). |
| 29 | `kpi_routes.py:867` | LOW | f-string missing placeholders (pyflakes). |
| 30 | `autocomplete_routes.py:19` | LOW | Unused imports (`typing.Optional`, `core.data_intelligence.name_tokens`). |
| 31 | `connect_routes.py:14` | LOW | Unused imports (`typing.AsyncGenerator`, `core.config.SCHEMA_DIR/PROCESSED_DIR/INSIGHTS_DIR/DATA_DIR`). |
| 32 | `data_routes.py:5` | LOW | Unused imports (`time`, `types`, `schema_agent`, `core.config.save_session`). |
| 33 | `kpi_routes.py:9` | LOW | Unused imports (`sqlite3`, `datetime`, `core.config.SCHEMA_DIR`, `core.deps.require_data`, `core.errors.*`, many `services.kpi_service.*`). |
| 34 | `insights_routes.py:29` | LOW | Unused imports from `services.insights_service`. |
| 35 | `prescription_routes.py:12` | LOW | Unused import `time`. |
| 36 | `hypothesis_routes.py:3` | LOW | Unused import `re`. |
| 37 | `rl_routes.py:15` | LOW | Unused import `core.config.get_session`. |
| 38 | `schema_routes.py:189` | LOW | Unused local `n_total`. |
| 39 | `auth_routes.py:217` | LOW | Unused local `user_id`. |
| 40 | `intelligence_routes.py:332` | LOW | Unused locals `did`, `session`. |
| 41 | `predictive_routes.py:1390` | LOW | Unused locals `goal_sql`, `goal_result`. |
| 42 | `export_routes.py:380` | LOW | Unused local `cat`. |
| 43 | `connect_routes.py:1350` | LOW | Redefinition of unused `session_status`. |
| 44 | `kpi_routes.py:196` | LOW | Redefinition of unused `SCHEMA_DIR`. |
| 45 | `kpi_routes.py:259` | LOW | Redefinition of unused `sqlite3`. |
| 46 | `document_routes.py:1002` | LOW | Redefinition of unused `DATA_DIR` (adjacent audited router; noted for consistency). |
| 47 | `insights_routes.py:2002` | LOW | Unused local `sqlite_compat`. |
| 48 | `feedback_routes.py:196` | LOW | `save_preferences` accepts arbitrary `payload: dict` and writes selected keys without schema validation. |
| 49 | `rl_routes.py:53` | LOW | `post_event` returns 200 on success; no explicit 201/202 status code. |
| 50 | `workspace_routes.py:241` | LOW | `create_webhook` does not enforce HTTPS or SSRF-safe URL validation at route layer. |
| 51 | `settings_routes.py:61` | LOW | `save_provider` stores API key after validation but error detail uses `provider_key_error`; no rate limit beyond global heavy limiter. |
| 52 | `copilot_routes.py:326` | LOW | `copilot_endpoint` is POST `""` under prefix; non-obvious path (`/api/copilot`) and relies on prefix. |

### 4.3 Missing test / coverage gaps
- No dedicated contract tests for most routers: `connect_routes`, `query_routes`, `kpi_routes`, `predictive_routes`, `prescription_routes`, `insights_routes`, `intelligence_routes`, `workspace_routes`, `export_routes`, `integrations_routes`, `rl_routes`, `feedback_routes`, `autocomplete_routes`, `schema_routes`, `settings_routes`, `verification_routes`, `hypothesis_routes`, `hypothesis_investigation_routes`.
- Only `tests/test_aria_api.py` and `tests/test_security_guards.py` exercise API behavior broadly.
- Optional export dependency 501 path (`openpyxl`/`python-pptx` absent) not covered.
- Slack integration endpoint (`/api/integrations/slack/command`) has no tests.
- Duplicate `/session/status` aliases and stacked GET/POST `/hypotheses` behavior not covered.
- `body: dict` verification endpoints lack schema/contract tests.

### 4.4 Verdict (API layer)
**Healthy / production-usable with hygiene gaps.** The audited API layer imports and wires cleanly, applies authentication consistently, and uses established guards (`require_writable`, `require_data`, `sanitize_error`, SSRF allowlists, read-only SQL guards). No critical undefined-helper or import errors. Primary issues are convention drift (missing `model_config = ConfigDict(extra="allow")` on most request models), unused imports/dead locals, inconsistent mobile-write policy on some POST endpoints, and thin automated coverage. No critical blockers.

---

## 5. Backend — Document Module (deep audit, prior session)

**Audited (prior session):** `api/document_routes.py`, `api/insight_rag_routes.py`, `insight_rag/service.py`, `insight_rag/storage.py`, `services/reingest_scheduler.py`, frontend `Documents.tsx`, `api.js`.

### 5.1 Issues found & fixed (this session)

| # | File:line | Sev | Issue (original) | Status |
|---|---|---|---|---|
| 1 | `insight_rag/service.py:263,410` (was) | CRITICAL | `datetime`/`timezone` never imported → every ingestion `NameError`. | **Fixed** (added `_dt` import + replaced calls). |
| 2 | `insight_rag/service.py` (was) | CRITICAL | `_classify_document` and `_sha256_file` referenced but never defined (`def` lines missing) → every ingestion `NameError`. | **Fixed** (added both defs). |
| 3 | `insight_rag/service.py` (was) | CRITICAL | Missing `uuid` import → `NameError` on `document_id = str(uuid.uuid4())`. | **Fixed**. |
| 4 | `insight_rag/service.py:145-154` (was) | HIGH | `InsightPDFRAG.__init__` hard-raised when provider not hosted → blocked offline ingestion. | **Fixed** (made `_hosted` flag; vector indexing best-effort). |
| 5 | `services/reingest_scheduler.py:79` | CRITICAL | `_run_job` called `InsightPDFRAG(uid)` without required `insight_agent` → every scheduled job crashed with `TypeError`. | **Fixed** (rewrote to use `RAGMetadataStore` directly). |
| 6 | `services/reingest_scheduler.py:85-91` | HIGH | Scheduled jobs didn't re-ingest; only touched manifest. | **Fixed** (now marks `last_reingested` per doc). |
| 7 | `services/reingest_scheduler.py:99-133` | HIGH | `_tick` read/wrote `JOBS_PATH` without `_lock`; `_save_jobs` non-atomic; `start()` check-then-act race. | **Fixed** (locking + atomic `os.replace` + lock in `start()`). |
| 8 | `api/document_routes.py:494` | HIGH | `search_document` had no `@router` decorator → endpoint never registered. | **Fixed** (added decorator). |
| 9 | `api/document_routes.py:578,584` | HIGH | `ask_documents` used non-existent `"copilot"` model role → answer path always failed. | **Fixed** (switched to `"semi"` + DeepSeek fallback). |
| 10 | `api/document_routes.py:140-155` | HIGH | `delete_document` always constructed `UserPGVectorStore` even when `chunk_ids=[]` → deletion failed for offline docs. | **Fixed** (skip vector store when empty). |
| 11 | `api/document_routes.py:785-823,1024-1048` | MEDIUM | `get_shared_document` and `documents_shared_with_me` leaked `share_token`/`shared_with`. | **Fixed** (stripped sensitive fields). |
| 12 | `api/insight_rag_routes.py` (list/delete) | MEDIUM | `list_pdf_documents` leaked sensitive fields; `delete_pdf_document` left orphaned on-disk files. | **Fixed** (stripped fields + unlink files). |
| 13 | `api/document_routes.py` (export) | LOW | Export filename header injection risk. | **Fixed** (sanitized `safe_title`). |
| 14 | `api/document_routes.py` (`_sanitize_document_id`) | LOW | Regex `^[a-zA-Z0-9_-]+$` too loose vs storage's 8–80 char requirement. | **Fixed** (tightened to `^[a-zA-Z0-9_-]{8,80}$`). |
| 15 | `insight_rag/summary_retry.py` | HIGH | Didn't forward new `document_only` kwarg → `TypeError` in chat. | **Fixed** (forwarded kwarg). |
| 16 | `insight_rag/scope_layer.py` | HIGH | New `_hosted` check at `chat()` entry. | **Fixed** (raises clear error when LLM unavailable). |
| 17 | Frontend `Documents.tsx` | HIGH | No in-page upload; chat only rendered raw passages (not synthesized answer); no degraded-mode banner. | **Fixed** (added upload affordance, degraded banner, `askDocuments` integration with citation chips). |
| 18 | `api.js` | MEDIUM | No `uploadDocument`/`getRagHealth`/`askDocuments` helpers. | **Fixed** (added). |

### 5.2 Remaining document-module issues (not yet fixed)

| # | File:line | Sev | Issue |
|---|---|---|---|
| R1 | `api/document_routes.py` (`retry_document`) | HIGH | Only reads legacy `document_processor` store; canonical docs return 404. Needs migration to canonical adapter. |
| R2 | `insight_rag/storage.py` (`_safe_id`) | MEDIUM | Raises unhandled `ValueError` on short IDs. |
| R3 | `insight_rag/storage.py` (`get_user_vector_store`) | MEDIUM | Global lock serializes all users (scalability). |
| R4 | `api/document_routes.py` | MEDIUM | BM25 lexical fallback result is computed but discarded (dead code path). |
| R5 | `api/document_routes.py` | MEDIUM | Chunk read bypasses canonical loader validation. |
| R6 | `api/connect_routes.py` (`/connect_pdf`) | MEDIUM | Bridge omits `chunk_ids`/`vector_indexed` → document gap in list. |
| R7 | `insight_rag/storage.py` | LOW | Vector-store cache cap (64) may grow unbounded under many users. |

### 5.3 Verdict (document module)
**Improved from "pretty much not useful" to functional.** Critical ingestion crash (NameError) fixed; offline ingestion works; summaries/answers now generate natural-language output via LLM fallback; upload + degraded banner + synthesized answers with citations wired into UI. Remaining work is migration/consistency + scalability (R1–R7).

---

## 6. Frontend (excluding `Documents.tsx`)

**Audited:** `src/`, `src/figma/`, `src/components/`, `src/utils/`, `src/services/api.js`, `tests/`, configs.

### 6.1 File status summary

| Directory | Purpose | Health |
|---|---|---|
| `src/` (root) | `main.jsx` mounts React root + ToastProvider; `aria-enhance.css` styling only. | Good |
| `src/components/` | `Toast.jsx` functional. | Minor leak (auto-dismiss timer not cleared on unmount) |
| `src/figma/` | `App.tsx` main state owner; components (`AppShell`, `MiniAria`, `FeedbackPopup`) functional; lib helpers sound. | Lifecycle/cleanup gaps |
| `src/figma/pages/` | Large pages (Dashboard, AIAnalytics, Data, Predictive, Intelligence, Insights, Copilot) build & typecheck cleanly. | Race conditions in polling/timeouts |
| `src/services/` | `api.js` central client robust (timeout, 401, request IDs). Several unused helpers. | Good core |
| `src/utils/` | `storage.js` versioned storage sound (but `ttlMs` ignored); `authStorage.js` cookie-based auth bypasses centralized client. | Minor |
| `tests/` | Playwright E2E + audit suite (audit suite ignored by default config). | Dormant audit specs |
| Configs (`playwright.config.cjs`, `package.json`, `index.html`, `vite.config.js`) | Coherent; build succeeds. | Good |

### 6.2 Issues (frontend)

| # | File:line | Sev | Issue |
|---|---|---|---|
| 1 | `src/figma/App.tsx:596` | HIGH | File-upload polling loop (`while (Date.now() < deadline)`) has no cancellation on unmount/navigation → state updates after teardown. |
| 2 | `src/figma/App.tsx:375` | HIGH | `handleLLMSelect` fires unawaited session/schema restore IIFE with no cancellation → stale updates after navigation. |
| 3 | `src/figma/App.tsx:155` | MEDIUM | Boot session probe closure captures initial `page`; admin redirect can use stale page state. |
| 4 | `src/figma/pages/Predictive.tsx:703` | MEDIUM | `setTimeout(... fetchForecast ...)` in `useAutomatic` is not cleared → can fire after dependencies change. |
| 5 | `src/figma/pages/Intelligence.tsx:2116` | MEDIUM | `window.open('/api/intelligence/reports/.../html')` hardcodes `/api` instead of using `API_BASE`/`resolvePath`. |
| 6 | `src/figma/pages/Copilot.tsx:147` | MEDIUM | `chatsKey` memoized with empty deps → per-user storage key can stay stale if identity changes. |
| 7 | `src/figma/pages/Data.tsx:148` | MEDIUM | Connection-health fetch uses mutable ref gate; rapid connect/disconnect toggles can trigger stale fetch resolution. |
| 8 | `src/figma/components/MiniAria.tsx:278` | MEDIUM | `setSuggestions` updater performs async side effects → violates React purity. |
| 9 | `src/figma/components/Toast.jsx:26` | LOW | Auto-dismiss `setTimeout` not cleared on unmount. |
| 10 | `src/figma/components/AppShell.tsx:105` | LOW | Notification polling interval keeps running while hidden. |
| 11 | `src/figma/pages/Dashboard.tsx:2234` | LOW | `onBlur` setTimeout (200ms) has no cleanup. |
| 12 | `src/utils/storage.js:121` | LOW | `storage.get` accepts `ttlMs` but ignores it (`void ttlMs`). |
| 13 | `src/utils/authStorage.js:125` | LOW | `authRequest` bypasses centralized `apiFetch` (no request ID/timeout normalization). |
| 14 | `src/figma/pages/Insights.tsx:1106` | LOW | Delete/save insight calls not guarded against in-flight duplicates. |
| 15 | `src/figma/components/DocumentChat.tsx:66` | LOW | Conversation turns keyed by array index → inefficient reconciliation on reorder. |

### 6.3 Dead code (frontend)
- `src/services/api.js`: unused exports `connectFile`, `connectPdf`, `getQuestionSuggestions`, `submitFeedback`, and legacy `loginUser` (documented as retained but uncalled).
- `tests/e2e/audit/**` excluded from the default Playwright gate → dormant unless run with its own config.

### 6.4 Verdict (frontend)
**Moderate.** The frontend builds and typechecks cleanly; the central API client is well-hardened. Main risk is lifecycle/async hygiene (uncancelled polling, timeouts, stale closures) in `App.tsx` and a few large pages, plus unused client helpers. No critical compile or endpoint-wiring failures in the audited non-Document sections. Recommended next step: harden cancellation/cleanup in the high-severity async flows before release.

---

## 7. Documents.tsx-specific issues (already fixed in this session)

Covered in §5.1 #17–18 and the prior session. Key remaining concerns in `Documents.tsx` itself: `fetchAll` fires untracked per-document summary fetches and mutates state after unmount/race (MEDIUM); "To dataset" button only toasts success and ignores returned `db_uri`/tables (HIGH — needs follow-up action wiring).

---

## 8. Cross-cutting observations

1. **Dual-store drift risk is the largest architectural liability.** Legacy `document_processor/` (FAISS/MiniLM) coexists with canonical `insight_rag/` (PGVector). `/api/connect_pdf` and `retry_document` still read the legacy store. Unifying ingestion is the highest-impact remaining work (see §5.2 R1, R6).
2. **Convention drift on request models.** Most routers lack `model_config = ConfigDict(extra="allow")`, so frontend payloads with extra fields are rejected. This is a systemic, low-risk-to-fix issue across ~18 routers.
3. **Heavy service files.** `services/intelligence_service.py` and `services/insights_service.py` are large and carry many unused imports/locals — cleanup candidates, not blockers.
4. **Legacy duplicate modules.** Top-level `goal_agent.py`/`schema_agent.py`/`insight_agent.py`/`prescription_agent.py` shadow the canonical packages and are a drift risk. Recommend deletion after confirming no external importers.
5. **Test coverage gaps.** ~18 routers have no dedicated contract tests; the audit/E2E suite is dormant by default.

---

## 9. Recommended priority order for next work

1. **Unify document stores** — migrate `/api/connect_pdf` and `retry_document` to canonical ingestion (fixes R1, R6, eliminates dual-store drift). *Highest impact.*
2. **Harden frontend async lifecycle** — cancel polling/timeouts in `App.tsx` upload flow and `Predictive.tsx` (§6.2 #1–4).
3. **Add `ConfigDict(extra="allow")`** to all request models (§4.2 #3–18) — systemic, low-risk.
4. **Slack signature verification** (§4.2 #23) — security.
5. **Webhook SSRF/HTTPS enforcement** (§4.2 #22, #50) — security.
6. **Admin overview DB-error path** (§2.2 #1) — medium.
7. **Remove legacy duplicate modules + shims** (§3.3, §2.3) — cleanup.
8. **Add contract tests** for the ~18 untested routers (§4.3).
9. **"To dataset" follow-up wiring** in `Documents.tsx` (§7).
10. **Cosmetic cleanup**: unused imports/locals across services and API (do in a single automated pass).

---

## 10. Overall health verdict

**HEALTHY / production-usable, with hygiene gaps and one architectural liability.**

- Import/wiring gates pass; 196 API routes registered; frontend builds and typechecks cleanly.
- Security posture is strong (PBKDF2 600k, DPAPI, SSRF validation, readonly SQL guards, rate limits, CSP, trusted hosts, canonical error shapes).
- AI pipeline is healthy (949/950 tests pass; the single failure is an environment-driven model-name mismatch).
- The document module — previously "pretty much not useful" — is now functional: ingestion no longer crashes, offline mode works, summaries/answers generate natural language, and the UI has upload + degraded banner + synthesized answers with citations.
- Remaining work is dominated by (a) unifying the dual document store, (b) frontend async-lifecycle hardening, and (c) convention drift (request-model `extra="allow"`) plus test coverage — none of which are blockers.

---

---

## 11. Follow-up pass — completed high-impact work

The following items from §9 were implemented and verified (import gate + frontend typecheck/lint/build + targeted pytest all green):

1. **`ConfigDict(extra="allow")`** added to every Pydantic request model across all 19 `api/*.py` routers that lacked it (convention drift resolved).
2. **Slack signature verification** added to `/api/integrations/slack/command` (`_verify_slack_signature`, HMAC-SHA256 over `v0:ts:body`, 5-min tolerance, backward-compatible when `SLACK_SIGNING_SECRET` unset).
3. **Webhook SSRF/HTTPS guard** added to `POST /api/workspace/webhooks` (`_validate_webhook_url`: http(s) only, blocks private/loopback/link-local/reserved hosts via IP resolution, requires https for non-local hosts).
4. **Frontend async-lifecycle hardening**: `App.tsx` upload polling now bails on unmount via `uploadCancelledRef`; stale `page` capture in the boot session probe fixed via `pageRef`; `Predictive.tsx` `useAutomatic` timer tracked in `useAutomaticTimerRef` and cleared.
5. **Document module** (prior pass): ingestion crash fixed, offline ingestion, natural-language summaries/answers, in-page upload, degraded banner, synthesized answer + citations.

Remaining open items: dual-store unification (R1/R6 in §5.2 — verified that `connect_pdf` already uses canonical `PDFIngestion`, so drift is smaller than initially assessed), legacy duplicate module removal, and contract tests for untested routers.

---

## 12. Forecast page investigation (follow-up)

**Symptom:** the Predictive/Forecast page appeared to produce no result.

**Root causes found and fixed:**

1. **Backend — overly strict source check** (`api/predictive_routes.py:945`): `generate_forecast` required a non-empty `session["db"]` dict and returned `400 "No database configuration found."` for CSV/SQLite sessions that carry only `db_uri` (or legacy `csv_db_path`). Eligibility accepted those sessions, so the page could report "eligible" and then fail on build. Now it matches `_build_engine` behaviour and falls back to `db_uri`/`csv_db_path`.
2. **Frontend — auto-fetch deadlock race** (`aria-frontend/src/figma/pages/Predictive.tsx`): the auto-fetch effects set `autoFetchRef.current = key` before the debounce timer fired. If the effect re-ran (eligibility/context/dependency update), its cleanup cleared the timer while the ref still blocked re-scheduling — the page stayed empty until the user manually clicked "Build forecast". The key is now set inside the timer callback, so a re-run can schedule again.

**Verified:** end-to-end TestClient flow (register → CSV upload → `/api/predictive/eligibility` → `/api/predictive/forecast`) returns `ok:true` with 24 historical + 6 forecast points, backtested accuracy 84.9% (preliminary). Added `tests/test_predictive_forecast_route.py` (3 tests: CSV db dict, db_uri-only legacy session, document-source refusal) — all pass. Frontend typecheck + build pass.

*Report compiled from four parallel subagent audits (core/infra, AI pipeline, API layer, frontend) plus targeted document-module and reingest-scheduler audits. All findings reference concrete `file:line` locations verified against the actual code.*
