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

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Make the project root importable regardless of the launching directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv()

from core.config import STATIC_DIR  # noqa: E402
from llm_provider import PROVIDERS  # noqa: E402
from api import auth_routes, connect_routes, query_routes, schema_routes  # noqa: E402

app = FastAPI(title="ARIA Testing UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(connect_routes.router)
app.include_router(schema_routes.router)
app.include_router(query_routes.router)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/providers")
def providers():
    """Return provider metadata (labels + privacy context) for the UI."""
    return {
        "providers": {
            name: {"label": meta["label"], "privacy": meta["privacy"], "models": meta["models"]}
            for name, meta in PROVIDERS.items()
        }
    }


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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

    requested_port = int(os.getenv("ARIA_PORT", "8000"))
    port = _resolve_port(requested_port)
    print(f"ARIA Testing UI running at http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
