"""ARIA FastAPI application entry point.

Wires together the route modules under ``api/`` and exposes the public
endpoints (``/``, ``/api/providers``). Run with:

    python app.py
    uvicorn app:app
"""

import os
import socket
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Make the project root importable regardless of the launching directory.
# core.config loads .env centrally on first import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import STATIC_DIR, BASE_DIR  # noqa: E402
from core.checks import run_checks  # noqa: E402
from llm_provider import PROVIDERS  # noqa: E402
from api import auth_routes, connect_routes, query_routes, schema_routes, document_routes, kpi_routes, copilot_routes, hypothesis_routes, settings_routes, feedback_routes, autocomplete_routes, data_routes  # noqa: E402

app = FastAPI(title="ARIA Testing UI")

_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000,http://localhost:5173,http://127.0.0.1:5173",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_routes.router)
app.include_router(connect_routes.router)
app.include_router(schema_routes.router)
app.include_router(query_routes.router)
app.include_router(document_routes.router)
app.include_router(kpi_routes.router)
app.include_router(copilot_routes.router)
app.include_router(hypothesis_routes.router)
app.include_router(settings_routes.router)
app.include_router(feedback_routes.router)
app.include_router(autocomplete_routes.router)
app.include_router(data_routes.router)

from api import insights_routes
app.include_router(insights_routes.router)

from api import predictive_routes
app.include_router(predictive_routes.router)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Return a clean JSON 500 with guidance instead of a raw stack trace page."""
    import logging
    import traceback

    logger = logging.getLogger("uvicorn.error")
    logger.exception("Unhandled error on %s", request.url.path)
    tb = traceback.format_exc()
    logger.error("Full traceback:\n%s", tb)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"An internal error occurred: {str(exc)}"
        },
    )


@app.on_event("startup")
def startup_checks():
    """Log a health report at startup; the app still starts on non-critical gaps."""
    import logging

    from core.checks import run_checks

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
# Use StaticFiles directly at root with html=True for SPA fallback
from fastapi.staticfiles import StaticFiles
app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")
# Also serve root files (favicon, index.html) via direct response
@app.get("/")
def index():
    prod_index = DIST_DIR / "index.html"
    if prod_index.exists():
        return FileResponse(prod_index)
    return FileResponse(STATIC_DIR / "index.html")

# Fallback: any unmatched route -> index.html (SPA routing)
@app.get("/{full_path:path}")
def catch_all(full_path: str):
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
