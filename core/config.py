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
from core.secret_box import decrypt, encrypt, PREFIX  # noqa: E402

for _name, _value in list(os.environ.items()):
    if isinstance(_value, str) and _value.startswith(PREFIX):
        try:
            os.environ[_name] = decrypt(_value)
        except Exception:
            pass


# Strict provider isolation: each hosted provider resolves its key ONLY from
# its own saved key or its own env var. Local (Ollama) never uses any API key.
# There is intentionally no cross-provider fallback (e.g. DeepSeek must never
# silently pick up GROQ_API_KEY).
PROVIDER_ENV_KEYS = {
    "cloud": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "omniroute": "OMNIROUTE_API_KEY",
    "local": None,
}


def resolve_provider_key(provider_name, api_keys=None):
    """Return the API key for exactly this provider, or None.

    Order: per-provider saved key -> provider's own env var. Local always
    returns None (Ollama needs no key and must never receive one).
    """
    if provider_name == "local":
        return None
    saved = (api_keys or {}).get(provider_name)
    if saved:
        return saved
    env_var = PROVIDER_ENV_KEYS.get(provider_name)
    if env_var:
        return os.getenv(env_var) or None
    return None


def _encrypt_api_keys(api_keys):
    """Encrypt per-provider API keys for at-rest storage.

    Plaintext values get `enc1:` prefix via DPAPI; already-encrypted
    values pass through unchanged. Non-string values are left as-is.
    """
    if not isinstance(api_keys, dict):
        return api_keys
    out = {}
    for k, v in api_keys.items():
        if isinstance(v, str) and v and not v.startswith(PREFIX):
            try:
                out[k] = encrypt(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def _decrypt_api_keys(api_keys):
    """Decrypt at-rest API keys, preserving plaintext for migration.

    Existing plaintext entries (pre-migration) are returned as-is so
    they remain usable; they are re-encrypted on next save_session.
    """
    if not isinstance(api_keys, dict):
        return api_keys
    out = {}
    for k, v in api_keys.items():
        if isinstance(v, str) and v.startswith(PREFIX):
            try:
                out[k] = decrypt(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def _decrypt_session_keys(session):
    """Return a copy of session with api_keys decrypted for runtime use."""
    if not isinstance(session, dict):
        return session
    keys = session.get("api_keys")
    if isinstance(keys, dict):
        session = dict(session)
        session["api_keys"] = _decrypt_api_keys(keys)
    # Rebuild relational db_uri (no longer persisted to disk) from the
    # encrypted `db` config so restarted sessions keep working.
    try:
        if session.get("db_type") in ("postgresql", "mysql") and not session.get("db_uri"):
            cfg = session.get("db")
            if isinstance(cfg, dict) and cfg.get("host") and cfg.get("db"):
                from core.secret_box import decrypt as _dec
                pwd = cfg.get("password")
                if isinstance(pwd, str) and pwd.startswith(PREFIX):
                    try:
                        pwd = _dec(pwd)
                    except Exception:
                        pwd = None
                if pwd:
                    from urllib.parse import quote_plus as _qp
                    scheme = "mysql+pymysql" if session.get("db_type") == "mysql" else "postgresql+psycopg2"
                    session["db_uri"] = (
                        f"{scheme}://{_qp(str(cfg.get('user', '')))}:{_qp(str(pwd))}"
                        f"@{cfg.get('host')}:{cfg.get('port')}/{cfg.get('db')}"
                    )
    except Exception:
        pass
    return session

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
PROVIDER_NAMES = {"local", "cloud", "deepseek", "omniroute"}
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
_SESSION_FILE_MTIME: float | None = None

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
                loaded = _decrypt_session_keys(loaded)
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
            api_key = resolve_provider_key(name, session.get("api_keys", {}))
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
    global _SESSION_FILE_MTIME
    with SESSION_LOCK:
        # mtime-gated reconcile: avoid re-reading/parsing session_store.json
        # on every request. Only reload when the file actually changed.
        # save_session updates _SESSION_FILE_MTIME so our own writes never
        # trigger a redundant reload; external writes still get picked up.
        try:
            import json as _json
            if SESSION_STORE_PATH.exists():
                mtime = SESSION_STORE_PATH.stat().st_mtime
                if _SESSION_FILE_MTIME is None or mtime != _SESSION_FILE_MTIME:
                    data = _json.loads(SESSION_STORE_PATH.read_text(encoding="utf-8"))
                    for uid_str, (created, session) in data.items():
                        uid = int(uid_str)
                        if uid not in SESSION_STORE or SESSION_STORE[uid][0] < float(created):
                            loaded = dict(session)
                            from pathlib import Path as _P
                            for k in ("schema_path", "processed_path", "insights_path"):
                                if k in loaded and isinstance(loaded[k], str):
                                    loaded[k] = _P(loaded[k])
                            loaded = _decrypt_session_keys(loaded)
                            SESSION_STORE[uid] = (float(created), loaded)
                    _SESSION_FILE_MTIME = mtime
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
    """Persist a modified session copy back to the store and to disk.

    In-memory SESSION_STORE keeps decrypted runtime keys; only the
    on-disk JSON copy carries encrypted `api_keys`.
    """
    now = time.time()
    with SESSION_LOCK:
        SESSION_STORE[user_id] = (now, session)
    # Also write to disk so sessions survive server restarts.
    try:
        import json as _json
        disk_store = {}
        for uid, (created, sess) in SESSION_STORE.items():
            sess_disk = dict(sess)
            if isinstance(sess_disk.get("api_keys"), dict):
                sess_disk["api_keys"] = _encrypt_api_keys(sess_disk["api_keys"])
            # Never persist live provider objects; they are reconstructed
            # via _ensure_provider from provider_name + api_keys.
            if not isinstance(sess_disk.get("provider"), (str, type(None))):
                sess_disk["provider"] = None
            # Never persist relational db_uri (it embeds the DB password in
            # plaintext). In-memory SESSION_STORE keeps it for the live
            # session; on restart it is rebuilt from the encrypted `db`
            # config. sqlite/document URIs (file paths, no secret) are kept.
            # Same rule applies inside a stashed linked_db connection.
            try:
                if sess_disk.get("db_type") in ("postgresql", "mysql"):
                    sess_disk.pop("db_uri", None)
                _linked = sess_disk.get("linked_db")
                if isinstance(_linked, dict):
                    _linked = dict(_linked)
                    if _linked.get("db_type") in ("postgresql", "mysql"):
                        _linked.pop("db_uri", None)
                    sess_disk["linked_db"] = _linked
            except Exception:
                pass
            disk_store[str(uid)] = (created, sess_disk)
        tmp_path = SESSION_STORE_PATH.with_suffix('.tmp')
        tmp_path.write_text(_json.dumps(disk_store, default=str), encoding='utf-8')
        tmp_path.replace(SESSION_STORE_PATH)
        try:
            global _SESSION_FILE_MTIME
            _SESSION_FILE_MTIME = SESSION_STORE_PATH.stat().st_mtime
        except Exception:
            pass
    except Exception:
        pass


def get_session_for_request(request):
    """Resolve a session using the current request bearer token when available.

    Header-only: ?token= was removed because tokens in URLs leak into
    server/proxy logs and browser history.
    """
    token = None
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
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
