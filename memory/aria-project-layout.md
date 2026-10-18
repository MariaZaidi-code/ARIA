---
name: aria-project-layout
description: ARIA is a FastAPI + React analytics app; the figma layer under aria-frontend/src/figma/ is the single mounted SPA
metadata:
  type: reference
---

# ARIA Project Layout

## Frontend: `aria-frontend/src/figma/` (single SPA)
- Entry: `aria-frontend/src/main.jsx` mounts `<App />` from `figma/App.tsx` inside `ToastProvider` (from `src/components/Toast.jsx`) — there is no root `App.jsx` and no `src/pages/` anymore.
- `App.tsx` — router (switch on `page` state), passes connection/question/goal props down to pages.
- `pages/` — Dashboard, AIAnalytics, Insights, Predictive, Intelligence, Data, Copilot, Documents, History, Settings (Prescription/Hypothesis pages removed; hypothesis = "Investigate why" inside AI Analytics/Insights).
- `components/AppShell.tsx` — shell layout (sidebar nav, header with dbName, notifications bell polling `/api/workspace/notifications`).
- `components/MiniAria.tsx` — floating robot assistant (bottom-right, all pages except Copilot).
- `components/FeedbackPopup.tsx` — random RL feedback popup (bottom-left): 1–5 stars + comment → `POST /api/rl/feedback`. Guards: `navigator.webdriver` skip, once/session, 72h cooldown (`aria.v1.ui.feedback_popup` TTL), `VITE_FEEDBACK_PROBABILITY` (default 0.18).
- `lib/` — analysisContext.ts, charts.ts, format.ts, intelHelpers.ts.
- `index.css` — Tailwind CSS with dark mode, custom properties.
- Services: `aria-frontend/src/services/api.js` (unified fetch client, timeout knob `VITE_API_TIMEOUT_MS`, 60–120s clamp).

## Backend: repo root
- `app.py` — FastAPI main; mounts routers.
- `api/` — auth, connect, query, document, copilot, hypothesis, hypothesis_investigation, kpi, settings, feedback, intelligence, insights, insight_rag, prescription, predictive, data, schema, autocomplete, verification, rl, workspace, export, integrations routes.
- `goal_agent/`, `insight_agent/`, `prediction/`, `prescription_engine/`, `hypothesis_engine/`.
- `schema_agent/` — legacy schema stack (deprecated); `schema_engine/` — canonical schema stack for new code.
- `llm_provider.py` — accepts `api_key` param; falls back to env keys per provider.
- `document_processor/` — PDF intelligence (extraction, chunking, embeddings, vector store).
- `data/` — SQLite `aria.db`, `schemas/`, `uploads/`, `users/`, `insight_rag/`, `preferences/`, `kaggle_retail_sales/`.

## RL Feedback Layer
- `core/rl.py` — `record_event` (append-only JSONL telemetry at `data/preferences/user_<id>/rl_events.jsonl`, 5MB/5k-line rotation), `RLPolicy` (`baseline-v1`; replaceable policy hook for future bandits/DQN/PPO), `rank_candidates`, `as_action`, `log_decision_activity`.
- Routes (router rate-limited `rl` 60/min): `POST /api/rl/event`, `GET /api/rl/events`, `POST /api/rl/feedback` (popup stars → reward `(rating-3)/2` in [-1, +1]), `GET /api/rl/status` (policy descriptor + reward summary; `model: null` until a trained policy exists), `POST /api/rl/rank` (active policy ranks pre-validated candidates only; strict `list[dict]`, max 200).
- Plug-in point for the trained model: swap the policy used by `api/rl_routes.py` (`RLPolicy` in `core/rl.py`) — routes/storage stay stable.

## Why-Question Analytics
- `classify_analytics` boosts explanation/root_cause when a cause word (`why/explain/caused`) meets a change word — "why did revenue drop last month" is explanation, not filtering.
- `goal_agent/analytics_intent.py` — `compute_change_drivers` decomposes the worst MoM (or biggest change) by IR dimensions via the executed query's own FROM/time expression (reconciles with shown numbers; rejects non-period labels); `build_change_hypothesis` words it as association, not cause.
- `api/query_routes.py` (`/api/ask`) runs change drivers for explanation/root_cause/hypothesis questions and fills `possible_drivers`/`hypothesis`/`comparison_period`; structural drivers remain the fallback.
- `core/analytical_result.py` — trend results get a period-aware entity and timeline story/why (no ranking voice on time series).

## Workspace Layer (monitors, targets, glossary, alerts, exports, Slack)
- `services/workspace_service.py` — per-user JSON workspace at `data/users/user_<id>/workspace/` (`monitors/targets/glossary/notifications/webhooks/integrations.json`, atomic writes). Glossaries store `{term, maps_to}`; `apply_glossary` rewrites `/api/ask` goals before intent classification (echoed as `glossary_applied`). Monitors only re-run SQL passing the read-only guard (`_safe_read_sql`: SELECT/WITH only, no multi-statement).
- `reporting/monitors.py` — cadence scheduler (hourly/daily/weekly; manual never auto-runs), 60s poll thread mirroring `reporting/digests.py`, lazy `ensure_started()` from workspace routes.
- `api/workspace_routes.py` (prefix `/api/workspace`) — monitors/targets/glossary/notifications/webhooks/integrations CRUD; monitor `check` returns `{ok, triggered, value, previous, message}`; check failures are recorded, never raised.
- `api/export_routes.py` (prefix `/api/export`) — `POST /story` with `format: pptx|xlsx|html` renders the client's exact envelope (title/answer/drivers/chart/table/optional SQL); needs `python-pptx`/`openpyxl`.
- `api/integrations_routes.py` (prefix `/api/integrations`) — `POST /slack/command?token=…`: token → user (`secrets.compare_digest`), mints a JWT (`auth.issue_token`), answers via loopback `/api/ask`. The sync path MUST run `_ask_sync` via `run_in_threadpool` (a same-loop blocking POST self-deadlocks uvicorn); deferred path (only `https://hooks.slack.com/` response_urls) acks instantly and posts from a background thread.
- Chart auto-annotation: `/api/ask` attaches `chart_spec.annotation {text, direction, current, previous, pct}` to trend charts with a change context (e.g. "Mar fell 28% vs Feb — mostly X (N% of the fall)").
- Frontend: `WorkspacePanels.tsx` (Settings → Workspace tab: glossary, targets, webhooks, Slack token), AppShell bell polls `/workspace/notifications` every 60s, Dashboard shows KPI target chips, AIAnalytics has Show-SQL/monitor/export buttons, annotation caption, and drill breadcrumbs; `workspaceApi` + `downloadStoryExport` live in `services/api.js`.

## Security
- User-applied provider keys: POST `/api/settings/providers` → stored in session dict `session["api_keys"][provider]` — **never written to disk**.
- `connect_routes.py` reads user key: `session.get("api_keys", {}).get(request.provider)`.

## Data Source Routes
- `POST /api/connect` → general
- `POST /api/connect/postgresql` / `POST /api/connect/mysql` → explicit engines
- `POST /api/connect_file` → CSV upload
- `POST /api/connect_pdf` → PDF upload (legacy document flow)
- `POST /api/insight/pdf/upload` → canonical Insight RAG upload
- `GET /api/schema` → fetch schema
- `GET/POST /api/settings/providers` → list/save user API keys
- (Line numbers intentionally omitted — routes move; grep the decorator.)

## Playwright E2E
- `aria-frontend/tests/e2e/` — specs: 01-auth-flow, 02-figma-pages, 03-main-pages, 04-data-connect, full-journey, intelligence, qa-all-pages, qa-connected-flow, cloud-llm-user-key (+ `auth-helper.cjs`). Decision Center specs removed with the page.
- `aria-frontend/playwright.config.cjs` — CommonJS, baseURL http://localhost:8000 (backend-served dist/ build; vite :5173 is dev-only).

## Dev Ports
- Frontend dev: `http://localhost:5173` (Vite)
- Backend: `http://localhost:8000` (FastAPI) with `/docs`

## DO NOT DELETE
- `aria-frontend/src/figma/` — the UI
- `aria-frontend/src/main.jsx` — SPA entry
- `.env` — encrypted keys
- `data/aria.db` — SQLite data
- `document_processor/` — PDF intelligence
- `api/connect_routes.py` — data source routes
