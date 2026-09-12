"""Shared application configuration and per-user runtime session state.

Environment variables are loaded exactly once here (from the project root's
``.env``) so every other module reads them without calling load_dotenv itself.
"""

import os
import threading
import time
from copy import deepcopy
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Secrets in .env may be stored DPAPI-encrypted (`enc1:<base64>`) so the file
# is unreadable at rest. Decrypt them back into the environment now that dotenv
# has loaded, before any module reads os.getenv for credentials.
from core.secret_box import decrypt, PREFIX  # noqa: E402

for _name, _value in list(os.environ.items()):
    if isinstance(_value, str) and _value.startswith(PREFIX):
        try:
            os.environ[_name] = decrypt(_value)
        except Exception:
            pass

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
# Dedicated folder for all schema mapping JSON files, keeping them out of the
# code tree (everything under data/ is gitignored and regenerable).
SCHEMA_DIR = DATA_DIR / "schemas"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
PROCESSED_DIR = ARTIFACTS_DIR / "processed_data"
INSIGHTS_DIR = ARTIFACTS_DIR / "insights"
FLOW_REPORTS_DIR = ARTIFACTS_DIR / "flow_reports"

for _dir in (ARTIFACTS_DIR, DATA_DIR, SCHEMA_DIR, PROCESSED_DIR, INSIGHTS_DIR, FLOW_REPORTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

SCHEMA_PATH = SCHEMA_DIR / "schema_mapping_latest.json"
PROCESSED_PATH = PROCESSED_DIR / "processed_data.json"
INSIGHTS_PATH = INSIGHTS_DIR / "insights.json"
SESSION_STORE_PATH = DATA_DIR / "session_store.json"

SOURCE_TYPES = {"relational", "semi-structured", "document"}
PROVIDER_NAMES = {"local", "cloud", "deepseek"}
DB_TYPES = {"postgresql", "mysql"}

DEFAULT_SESSION = {
    "provider": None,       # LLMProvider instance
    "provider_name": None,  # 'local' | 'cloud'
    "source_type": None,    # 'relational' | 'semi-structured'
    "db": None,             # relational DB config
    "db_type": "postgresql",  # 'postgresql' | 'mysql' (relational sources only)
    "db_uri": None,
    "db_name": None,        # name of the connected database / table
    "schema_path": SCHEMA_PATH,   # schema file for the active database
    "processed_path": PROCESSED_PATH,
    "insights_path": INSIGHTS_PATH,
    "dialect": "postgresql",     # 'postgresql'|'mysql' for relational, 'sqlite' for CSV/PDF
    "pending_history_id": None,  # most recent history row awaiting insights
}

SESSION = deepcopy(DEFAULT_SESSION)
SESSION_STORE: dict[int, tuple[float, dict]] = {}
SESSION_LOCK = threading.RLock()

# Load persisted sessions from disk (survives server restarts).
def _load_session_store():
    """Load persisted session store from disk."""
    try:
        import json as _json
        if SESSION_STORE_PATH.exists():
            data = _json.loads(SESSION_STORE_PATH.read_text(encoding="utf-8"))
            for uid_str, (created, session) in data.items():
                uid = int(uid_str)
                loaded = dict(session)
                # Restore Path types (JSON can't represent them)
                from pathlib import Path as _P
                for k in ("schema_path", "processed_path", "insights_path"):
                    if k in loaded and isinstance(loaded[k], str):
                        loaded[k] = _P(loaded[k])
                SESSION_STORE[uid] = (float(created), loaded)
    except Exception:
        pass

_load_session_store()

# Session store hygiene: cap the number of cached per-user sessions and drop
# sessions that have not been touched for SESSION_TTL_SECONDS. Prevents
# unbounded memory growth in long-running multi-user servers.
SESSION_MAX_USERS = 100
SESSION_TTL_SECONDS = 4 * 60 * 60  # 4 hours


def _ensure_provider(session):
    """Reconstruct the LLMProvider instance if session['provider'] is a string
    (happens after deserialization from disk where default=str serializes the
    LLMProvider object to its string representation)."""
    from llm_provider import create_provider
    prov = session.get("provider")
    if prov is None or isinstance(prov, str):
        name = session.get("provider_name")
        if name:
            api_keys = session.get("api_keys", {})
            env_key = os.getenv(f"{name.upper()}_API_KEY", os.getenv("GROQ_API_KEY"))
            api_key = api_keys.get(name) or env_key
            try:
                session["provider"] = create_provider(provider=name, api_key=api_key)
            except Exception:
                session["provider"] = None
        else:
            session["provider"] = None


def _copy_session(session):
    """Shallow-copy the session dict so callers can mutate keys without
    leaking changes to other requests.  Values like the LLM provider
    object contain thread locks and cannot be deep-copied."""
    return dict(session)


def get_session(user_id=None):
    """Return the current session for a user, or a fresh default copy.

    Returns a shallow copy of the session dict so each request gets its
    own dict but shares immutable / non-copyable values (LLM provider).
    Use ``save_session`` to persist modifications back to the store.
    """
    if user_id is None:
        return dict(DEFAULT_SESSION)

    now = time.time()
    with SESSION_LOCK:
        # Re-load from disk on every request so external writes (e.g. via
        # Python scripts) are picked up immediately without a server restart.
        try:
            import json as _json
            if SESSION_STORE_PATH.exists():
                data = _json.loads(SESSION_STORE_PATH.read_text(encoding="utf-8"))
                for uid_str, (created, session) in data.items():
                    uid = int(uid_str)
                    if uid not in SESSION_STORE or SESSION_STORE[uid][0] < float(created):
                        loaded = dict(session)
                        from pathlib import Path as _P
                        for k in ("schema_path", "processed_path", "insights_path"):
                            if k in loaded and isinstance(loaded[k], str):
                                loaded[k] = _P(loaded[k])
                        SESSION_STORE[uid] = (float(created), loaded)
        except Exception:
            pass

    now = time.time()
    with SESSION_LOCK:
        # Opportunistic cleanup of expired sessions.
        if len(SESSION_STORE) >= SESSION_MAX_USERS or (len(SESSION_STORE) > 10 and len(SESSION_STORE) % 5 == 0):
            expired = [
                uid for uid, (created, _session) in SESSION_STORE.items()
                if now - created > SESSION_TTL_SECONDS
            ]
            for uid in expired:
                del SESSION_STORE[uid]
            # If still at capacity, drop the oldest entry.
            while len(SESSION_STORE) >= SESSION_MAX_USERS:
                oldest = min(SESSION_STORE, key=lambda uid: SESSION_STORE[uid][0])
                del SESSION_STORE[oldest]

        entry = SESSION_STORE.get(user_id)
        if entry is None:
            entry = (now, dict(DEFAULT_SESSION))
            SESSION_STORE[user_id] = entry
        else:
            SESSION_STORE[user_id] = (now, entry[1])
        _ensure_provider(entry[1])
        return _copy_session(entry[1])


def save_session(user_id, session):
    """Persist a modified session copy back to the store and to disk."""
    now = time.time()
    with SESSION_LOCK:
        SESSION_STORE[user_id] = (now, session)
    # Also write to disk so sessions survive server restarts.
    try:
        import json as _json
        data = {str(uid): entry for uid, entry in SESSION_STORE.items()}
        tmp_path = SESSION_STORE_PATH.with_suffix('.tmp')
        tmp_path.write_text(_json.dumps(data, default=str), encoding='utf-8')
        tmp_path.replace(SESSION_STORE_PATH)
    except Exception:
        pass


def get_session_for_request(request):
    """Resolve a session using the current request bearer token when available."""
    token = None
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif request.query_params.get("token"):
        token = request.query_params.get("token")
    if not token:
        return get_session(None)
    try:
        import auth
        payload = auth.verify_token(token)
    except Exception:
        return get_session(None)
    if not payload:
        return get_session(None)
    return get_session(payload.get("user_id"))
