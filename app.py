"""ARIA FastAPI application entry point.

Wires together the route modules under ``api/`` and exposes the public
endpoints (``/``, ``/api/providers``). Run with:

    python app.py
    uvicorn app:app
"""

import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Make the project root importable regardless of the launching directory.
# core.config loads .env centrally on first import.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import STATIC_DIR, BASE_DIR  # noqa: E402
from core.checks import run_checks  # noqa: E402
from llm_provider import PROVIDERS  # noqa: E402
from api import auth_routes, connect_routes, query_routes, schema_routes, document_routes, kpi_routes, copilot_routes, hypothesis_routes, settings_routes, feedback_routes, autocomplete_routes, data_routes, insight_rag_routes, insights_routes, predictive_routes, prescription_routes, rl_routes  # noqa: E402
from core.ratelimit import limit, limit_heavy, limit_llm  # noqa: E402
from fastapi import Depends as _Depends  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup checks; failures stay visible but never crash import."""
    import logging
    report = run_checks()
    critical = report["critical"]
    if critical:
        logging.getLogger("uvicorn.error").error(
            "ARIA startup check: missing required packages -> %s", ", ".join(critical)
        )
    if not report["ollama"]["ok"]:
        logging.getLogger("uvicorn.error").warning(
            "ARIA startup check: %s", report["ollama"]["detail"]
        )
    logging.getLogger("uvicorn.error").info("ARIA startup checks complete.")
    yield


_enable_docs = os.getenv("ARIA_ENABLE_DOCS", "1").strip() not in {"0", "false", "no", "off"}
app = FastAPI(
    title="ARIA Testing UI",
    lifespan=lifespan,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # CSP is report-only friendly: allow same-origin + data/blob for charts/exports.
    if request.url.path.startswith("/docs") or request.url.path.startswith("/redoc"):
        pass
    else:
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:",
        )
    return resp


@app.middleware("http")
async def _request_id(request: Request, call_next):
    """Attach a stable request ID (t.txt-7): full tracebacks are logged
    server-side against it; clients only ever see the ID."""
    import uuid as _uuid

    rid = request.headers.get("X-Request-ID") or _uuid.uuid4().hex[:12]
    request.state.request_id = rid
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = rid
    return resp

_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000,http://localhost:5173,http://127.0.0.1:5173",
).split(",")
if "*" in [o.strip() for o in _cors_origins]:
    # "*" + allow_credentials is rejected by browsers anyway; drop it loudly
    # rather than running an insecure no-op config.
    import logging as _logging

    _logging.getLogger("uvicorn.error").warning(
        "CORS_ORIGINS contains '*', which is incompatible with allow_credentials; ignoring '*'."
    )
    _cors_origins = [o for o in _cors_origins if o.strip() != "*"] or ["http://localhost:8000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_routes.router)  # has its own login/register limiter
app.include_router(connect_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(schema_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(query_routes.router, dependencies=[_Depends(limit_llm())])
app.include_router(document_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(kpi_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(copilot_routes.router, dependencies=[_Depends(limit_llm())])
app.include_router(hypothesis_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(settings_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(feedback_routes.router, dependencies=[_Depends(limit("feedback", 60))])
app.include_router(autocomplete_routes.router, dependencies=[_Depends(limit("autocomplete", 180))])
app.include_router(data_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(insight_rag_routes.router, dependencies=[_Depends(limit_llm())])
app.include_router(insights_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(predictive_routes.router, dependencies=[_Depends(limit_llm())])
app.include_router(prescription_routes.router, dependencies=[_Depends(limit_heavy())])
app.include_router(rl_routes.router, dependencies=[_Depends(limit("rl", 60))])


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Return a clean JSON 500 with guidance instead of a raw stack trace page."""
    import logging
    import traceback

    rid = getattr(request.state, "request_id", "unknown")
    logger = logging.getLogger("uvicorn.error")
    logger.exception("Unhandled error on %s [rid=%s]", request.url.path, rid)
    tb = traceback.format_exc()
    logger.error("Full traceback [rid=%s]:\n%s", rid, tb)
    # Generic message to the client (detail is logged server-side only).
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong. Reference ID: " + rid,
            "request_id": rid,
        },
    )


@app.get("/api/health")
def health():
    """Live dependency/health status for ops and the UI."""
    return run_checks()


@app.get("/api/providers")
def providers():
    """Return provider metadata (labels + privacy context) for the UI."""
    return {
        "providers": {
            name: {"label": meta["label"], "privacy": meta["privacy"], "models": meta["models"]}
            for name, meta in PROVIDERS.items()
        }
    }


# Serve the built React frontend (aria-frontend/dist/) at root
DIST_DIR = BASE_DIR / "aria-frontend" / "dist"
# Mount dist contents so /assets/ resolves correctly (vite builds to /assets/)
# Guarded: missing build dir must not crash the backend (API still works).
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")
# Also serve root files (favicon, index.html) via direct response
@app.get("/")
def index():
    prod_index = DIST_DIR / "index.html"
    if prod_index.exists():
        return FileResponse(prod_index)
    return FileResponse(STATIC_DIR / "index.html")

# Fallback: any unmatched non-API route -> index.html (SPA routing).
# /api/* must never silently return HTML; unknown API paths return 404.
@app.get("/{full_path:path}")
def catch_all(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Unknown API endpoint."})
    prod_index = DIST_DIR / "index.html"
    if prod_index.exists():
        return FileResponse(prod_index)
    return FileResponse(STATIC_DIR / "index.html")


def _resolve_port(start_port: int = 8000, max_tries: int = 20) -> int:
    """Return the first free local port starting from the requested value."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free local port found between {start_port} and {start_port + max_tries - 1}.")


if __name__ == "__main__":
    import uvicorn

    try:
        requested_port = int(os.getenv("ARIA_PORT", "8000"))
    except (ValueError, TypeError):
        requested_port = 8000
    port = _resolve_port(requested_port)
    print(f"ARIA Testing UI running at http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
