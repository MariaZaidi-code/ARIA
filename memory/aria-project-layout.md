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
- `pages/` — Dashboard, AIAnalytics, Insights, Predictive, Prescription, Hypothesis, Data, Copilot, Documents, History, Settings.
- `components/AppShell.tsx` — shell layout (sidebar nav, header with dbName).
- `lib/` — analysisContext.ts, charts.ts, format.ts, intelHelpers.ts.
- `index.css` — Tailwind CSS with dark mode, custom properties.
- Services: `aria-frontend/src/services/api.js` (unified fetch client, timeout knob `VITE_API_TIMEOUT_MS`, 60–120s clamp).

## Backend: repo root
- `app.py` — FastAPI main; mounts routers.
- `api/` — auth, connect, query, document, copilot, hypothesis, hypothesis_investigation, kpi, settings, feedback, intelligence, insights, insight_rag, prescription, predictive, data, schema, autocomplete, verification, rl routes.
- `goal_agent/`, `insight_agent/`, `prediction/`, `prescription_engine/`, `hypothesis_engine/`.
- `schema_agent/` — legacy schema stack (deprecated); `schema_engine/` — canonical schema stack for new code.
- `llm_provider.py` — accepts `api_key` param; falls back to env keys per provider.
- `document_processor/` — PDF intelligence (extraction, chunking, embeddings, vector store).
- `data/` — SQLite `aria.db`, `schemas/`, `uploads/`, `users/`, `insight_rag/`, `preferences/`, `kaggle_retail_sales/`.

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
- `aria-frontend/tests/e2e/` — specs: 01-auth-flow, 02-figma-pages, 03-main-pages, 04-data-connect, 05-decision-detail, 06-view-details-chain, full-journey, intelligence, qa-all-pages, qa-connected-flow (+ `auth-helper.cjs`).
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
