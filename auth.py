"""User store, JWT auth, and per-user history for ARIA.

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib only, no bcrypt wheels).
Tokens are HS256 JWTs valid for TOKEN_TTL_DAYS. History is kept per user in a
local SQLite database (data/aria.db).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import jwt

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "aria.db"
JWT_ALGO = "HS256"


def _token_ttl_days() -> int:
    """Resolve JWT lifetime in days from ``TOKEN_TTL_DAYS``.

    Env contract (documented):
      - ``TOKEN_TTL_DAYS``: integer ``1..7`` days, default ``1``.
      - Unset or empty/whitespace -> ``1`` (intended default).
      - Out-of-range integers are clamped to ``1..7``.
      - Non-integer values raise ``ValueError`` (fail clearly, no silent
        fallback to an unsafe value).
    """
    raw = os.getenv("TOKEN_TTL_DAYS")
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return 1
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid TOKEN_TTL_DAYS={raw!r}: must be an integer 1..7 days."
        )
    return min(7, max(1, value))


TOKEN_TTL_DAYS = _token_ttl_days()


def _token_ttl_hours() -> int:
    raw = os.getenv("TOKEN_TTL_HOURS")
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        legacy = os.getenv("TOKEN_TTL_DAYS")
        if legacy not in (None, ""):
            try:
                return min(168, max(1, int(str(legacy).strip()) * 24))
            except (TypeError, ValueError):
                pass
        return 12
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(
            "Invalid TOKEN_TTL_HOURS=%r: must be an integer 1..168 hours." % raw
        )
    return min(168, max(1, value))


TOKEN_TTL_HOURS = _token_ttl_hours()
# New hashes use the current stronger work factor. Existing hashes carry
# their iteration count in the stored format and are transparently upgraded
# after a successful login (see authenticate), so deployments do not need a
# password-reset event to migrate existing users.
PBKDF2_ITERATIONS = 600_000

_USERNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]+")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")
EMAIL_VERIFICATION_TTL_HOURS = 24
AUTH_EVENT_RETENTION_DAYS = 180


def _is_production() -> bool:
    """Production mode flag (existing convention: ARIA_ENV=production)."""
    return (os.getenv("ARIA_ENV") or "").strip().lower() == "production"


def _load_secret() -> str:
    # JWT_SECRET env override wins (container/prod secret injection); the
    # file fallback preserves existing single-machine deployments.
    env_secret = (os.getenv("JWT_SECRET") or "").strip()
    if _is_production():
        # Fail fast in production: never autogenerate/persist a secret and
        # never fall back to a known/default value. Inject JWT_SECRET.
        if not env_secret:
            raise RuntimeError(
                "JWT_SECRET is required when ARIA_ENV=production. "
                "Inject a strong random secret (e.g. 64 hex chars) via the "
                "JWT_SECRET environment variable."
            )
        if len(env_secret) < 32:
            raise RuntimeError(
                "JWT_SECRET is too short for ARIA_ENV=production "
                f"({len(env_secret)} chars; need >= 32). Inject a strong "
                "random secret."
            )
        return env_secret
    if env_secret:
        return env_secret
    secret_path = BASE_DIR / "data" / ".jwt_secret"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    secret_path.write_text(secret, encoding="utf-8")
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass
    return secret


_SECRET_LOCK = threading.Lock()


def _signing_secret() -> str:
    """Resolve once on first use; keep the legacy auth.SECRET override contract."""
    with _SECRET_LOCK:
        value = globals().get("SECRET")
        if value is None:
            value = _load_secret()
            globals()["SECRET"] = value
        return value


def __getattr__(name):
    if name == "SECRET":
        return _signing_secret()
    raise AttributeError(name)


# Previous secret accepted for verification only (rotation: set JWT_SECRET to
# the new value and JWT_SECRET_PREVIOUS to the old one until tokens expire).
SECRET_PREVIOUS = (os.getenv("JWT_SECRET_PREVIOUS") or "").strip() or None


_SCHEMA_READY_PATHS: set[str] = set()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create auth tables once per database path (not on every request)."""
    key = str(DB_PATH)
    if key in _SCHEMA_READY_PATHS:
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            email TEXT,
            email_verified INTEGER NOT NULL DEFAULT 0
        )"""
    )
    user_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "email_verified" not in user_columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"
        )
    # Older frontend accounts used this reversible username mapping. Recover
    # their candidate address, but keep it unverified until the owner proves
    # control through the same email flow as new accounts.
    legacy_rows = conn.execute(
        "SELECT id, username FROM users WHERE email IS NULL"
    ).fetchall()
    for row in legacy_rows:
        username = str(row["username"] or "")
        if "_at_" not in username:
            continue
        candidate = username.replace("_at_", "@", 1).replace("_plus_", "+")
        if _EMAIL_RE.fullmatch(candidate):
            conn.execute(
                "UPDATE users SET email = ? WHERE id = ? AND email IS NULL",
                (candidate.lower(), row["id"]),
            )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique "
        "ON users(email COLLATE NOCASE) WHERE email IS NOT NULL"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            goal TEXT NOT NULL,
            sql_used TEXT,
            row_count INTEGER,
            columns TEXT,
            source_type TEXT,
            db_name TEXT,
            dialect TEXT,
            processed_json TEXT,
            insights_json TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS revoked_tokens (
            token_hash TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_verification_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS auth_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            page TEXT,
            occurred_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_events_type_time "
        "ON auth_events(event_type, occurred_at)"
    )
    conn.commit()
    _SCHEMA_READY_PATHS.add(key)


def _decode_token(token: str):
    """Decode with the current secret, falling back to the previous secret."""
    try:
        return jwt.decode(token, _signing_secret(), algorithms=[JWT_ALGO], options={"require": ["exp", "iat", "sub"]})
    except jwt.InvalidSignatureError:
        if SECRET_PREVIOUS:
            return jwt.decode(token, SECRET_PREVIOUS, algorithms=[JWT_ALGO], options={"require": ["exp", "iat", "sub"]})
        raise


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Busy-timeout + WAL: concurrent logins/history writes must not 500
    # with "database is locked". Retries handled by callers' short loops;
    # the timeout below covers the common contention window.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    _ensure_schema(conn)
    return conn


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def register(username: str, password: str) -> int:
    username = (username or "").strip()
    if len(username) < 3 or not _USERNAME_RE.fullmatch(username):
        raise ValueError("Username must be at least 3 characters using letters, digits, . _ -.")
    if len(password) < 8 or len(password) > 128:
        raise ValueError("Password must be 8-128 characters.")
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, _hash_password(password), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        return row["id"]
    except sqlite3.IntegrityError:
        raise ValueError("Username already taken.")
    finally:
        conn.close()


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > 254 or not _EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


def _legacy_email_username(email: str) -> str:
    return (
        email.lower()
        .replace("@", "_at_")
        .replace("+", "_plus_")
    )


def register_email(email: str, password: str) -> int:
    normalized = normalize_email(email)
    if len(password) < 8 or len(password) > 128:
        raise ValueError("Password must be 8-128 characters.")
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO users
               (username, password_hash, created_at, email, email_verified)
               VALUES (?, ?, ?, ?, 0)""",
            (
                _legacy_email_username(normalized),
                _hash_password(password),
                datetime.now(timezone.utc).isoformat(),
                normalized,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE", (normalized,)
        ).fetchone()
        return int(row["id"])
    except sqlite3.IntegrityError:
        raise ValueError("An account already exists for this email address.")
    finally:
        conn.close()


def create_email_verification_token(email: str) -> str | None:
    normalized = normalize_email(email)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, email_verified FROM users WHERE email = ? COLLATE NOCASE",
            (normalized,),
        ).fetchone()
        if not row or row["email_verified"]:
            return None
        conn.execute(
            """UPDATE email_verification_tokens SET used_at = ?
               WHERE user_id = ? AND used_at IS NULL""",
            (now.isoformat(), row["id"]),
        )
        conn.execute(
            """INSERT INTO email_verification_tokens
               (token_hash, user_id, expires_at, used_at)
               VALUES (?, ?, ?, NULL)""",
            (
                token_hash,
                row["id"],
                (now + timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS)).isoformat(),
            ),
        )
        conn.commit()
        return raw_token
    finally:
        conn.close()


def send_email_verification(email: str, token: str) -> None:
    """Send a one-time verification link using Gmail-compatible SMTP."""
    host = (os.getenv("ARIA_SMTP_HOST") or "").strip()
    username = (os.getenv("ARIA_SMTP_USERNAME") or "").strip()
    password = (os.getenv("ARIA_SMTP_PASSWORD") or "").strip()
    sender = (os.getenv("ARIA_SMTP_FROM") or username).strip()
    if not all((host, username, password, sender)):
        raise RuntimeError(
            "Email verification is not configured. Set ARIA_SMTP_HOST, "
            "ARIA_SMTP_USERNAME, ARIA_SMTP_PASSWORD, and ARIA_SMTP_FROM."
        )
    try:
        port = int(os.getenv("ARIA_SMTP_PORT", "587"))
    except ValueError as exc:
        raise RuntimeError("ARIA_SMTP_PORT must be a valid port number.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("ARIA_SMTP_PORT must be between 1 and 65535.")

    public_url = (
        os.getenv("ARIA_PUBLIC_URL") or "http://127.0.0.1:8000"
    ).strip().rstrip("/")
    if _is_production() and not public_url.startswith("https://"):
        raise RuntimeError("ARIA_PUBLIC_URL must use HTTPS in production.")
    verification_url = (
        f"{public_url}/?verify_email={quote(token, safe='')}"
    )
    message = EmailMessage()
    message["Subject"] = "Verify your ARIA email address"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Verify your email address to activate your ARIA account. "
        f"This link expires in {EMAIL_VERIFICATION_TTL_HOURS} hours:\n\n"
        f"{verification_url}\n\n"
        "If you did not request this account, you can ignore this email."
    )

    context = ssl.create_default_context()
    timeout = 15
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)


def verify_email_token(raw_token: str) -> str | None:
    token = (raw_token or "").strip()
    if not token or len(token) > 256:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        row = conn.execute(
            """SELECT t.user_id, u.email
               FROM email_verification_tokens t
               JOIN users u ON u.id = t.user_id
               WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ?
                 AND u.email_verified = 0""",
            (token_hash, now),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE users SET email_verified = 1 WHERE id = ?",
            (row["user_id"],),
        )
        conn.execute(
            "UPDATE email_verification_tokens SET used_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        conn.commit()
        return str(row["email"])
    finally:
        conn.close()


def authenticate_email(email: str, password: str) -> dict | None:
    try:
        normalized = normalize_email(email)
    except ValueError:
        normalized = ""
    if not normalized or not isinstance(password, str) or len(password) > 128:
        return None
    conn = _get_db()
    try:
        row = conn.execute(
            """SELECT id, username, password_hash, email, email_verified
               FROM users WHERE email = ? COLLATE NOCASE""",
            (normalized,),
        ).fetchone()
    finally:
        conn.close()
    if row and _verify_password(password, row["password_hash"]):
        if not row["email_verified"]:
            return {"user_id": int(row["id"]), "email": normalized, "verified": False}
        record_auth_event(int(row["id"]), "login")
        return {
            "user_id": int(row["id"]),
            "email": str(row["email"]),
            "username": str(row["email"]),
            "verified": True,
        }
    _verify_password(
        "dummy-password-for-timing",
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$" + "00" * 16 + "$" + "00" * 32,
    )
    return None


def record_auth_event(user_id: int, event_type: str, page: str | None = None) -> None:
    if event_type not in {"login", "page_visit"}:
        raise ValueError("Unsupported auth event.")
    if event_type == "page_visit" and (
        not page or len(page) > 64 or not re.fullmatch(r"[a-z][a-z0-9_-]*", page)
    ):
        raise ValueError("Invalid page identifier.")
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO auth_events (user_id, event_type, page, occurred_at) VALUES (?, ?, ?, ?)",
            (user_id, event_type, page, datetime.now(timezone.utc).isoformat()),
        )
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=AUTH_EVENT_RETENTION_DAYS)
        ).isoformat()
        conn.execute("DELETE FROM auth_events WHERE occurred_at < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


def authenticate(username: str, password: str) -> int | None:
    if not username or not isinstance(username, str):
        return None
    if not isinstance(password, str) or len(password) > 128:
        return None
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    finally:
        conn.close()
    if row and _verify_password(password, row["password_hash"]):
        # Upgrade weaker legacy hashes only after the password has already
        # verified. Compare-and-swap prevents a concurrent password update
        # from being overwritten with a hash of the older credential.
        try:
            stored = str(row["password_hash"] or "")
            _parts = stored.split("$")
            _stored_iters = int(_parts[1]) if len(_parts) == 4 else PBKDF2_ITERATIONS
            if _stored_iters < PBKDF2_ITERATIONS:
                conn = _get_db()
                try:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ? AND password_hash = ?",
                        (_hash_password(password), row["id"], stored),
                    )
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            # Authentication must remain available if a best-effort hash
            # migration encounters a transient database error.
            pass
        return row["id"]
    # Dummy hash to reduce user-enumeration timing oracle.
    _verify_password(
        "dummy-password-for-timing",
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$" + "00" * 16 + "$" + "00" * 32,
    )
    return None


def is_admin_email(email: str) -> bool:
    """Authorize the single email address configured as the ARIA owner."""
    configured = (os.getenv("ARIA_ADMIN_EMAIL") or "").strip().lower()
    candidate = (email or "").strip().lower()
    return bool(configured and candidate and candidate == configured)


def get_admin_overview() -> dict:
    """Return aggregate account, login, page-visit, and health data."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    conn = _get_db()
    try:
        users_total = int(conn.execute(
            "SELECT COUNT(*) FROM users WHERE email_verified = 1"
        ).fetchone()[0])
        users_new_7d = int(conn.execute(
            "SELECT COUNT(*) FROM users WHERE email_verified = 1 AND created_at >= ?",
            (cutoff,),
        ).fetchone()[0])
        analyses_total = int(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
        activity = conn.execute(
            """SELECT COUNT(*) AS analyses_7d,
                      COUNT(DISTINCT user_id) AS active_users_7d,
                      MAX(created_at) AS last_activity
               FROM history WHERE created_at >= ?""",
            (cutoff,),
        ).fetchone()
        logins = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN occurred_at >= ? THEN 1 ELSE 0 END) AS last_7d
               FROM auth_events WHERE event_type = 'login'""",
            (cutoff,),
        ).fetchone()
        visits = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN occurred_at >= ? THEN 1 ELSE 0 END) AS last_7d
               FROM auth_events WHERE event_type = 'page_visit'""",
            (cutoff,),
        ).fetchone()
        page_visits = conn.execute(
            """SELECT page, COUNT(*) AS total,
                      SUM(CASE WHEN occurred_at >= ? THEN 1 ELSE 0 END) AS last_7d
               FROM auth_events WHERE event_type = 'page_visit'
               GROUP BY page ORDER BY total DESC, page ASC""",
            (cutoff,),
        ).fetchall()
        recent_events = conn.execute(
            """SELECT event_type, page, occurred_at FROM auth_events
               ORDER BY id DESC LIMIT 12"""
        ).fetchall()
        active_users = conn.execute(
            """SELECT COUNT(DISTINCT user_id) FROM auth_events
               WHERE occurred_at >= ?""",
            (cutoff,),
        ).fetchone()[0]
        auth_store = "available"
        try:
            conn.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            auth_store = "unavailable"
            raise
        mail_configured = all(
            (os.getenv(name) or "").strip()
            for name in ("ARIA_SMTP_HOST", "ARIA_SMTP_USERNAME", "ARIA_SMTP_PASSWORD")
        ) and bool((os.getenv("ARIA_SMTP_FROM") or os.getenv("ARIA_SMTP_USERNAME") or "").strip())

        system = {
            "api": "available",
            "auth_store": auth_store,
            "email_delivery": "configured" if mail_configured else "not_configured",
        }
        try:
            from core.config import session_store_status
            session_status = session_store_status()
            system["session_store"] = (
                "available" if session_status.get("ok", True) else "degraded"
            )
        except (ImportError, AttributeError):
            system["session_store"] = "unknown"
        try:
            from core.checks import check_ollama, check_default_db, check_shared_store
            system["local_llm"] = (
                "available" if check_ollama().get("ok") else "unavailable"
            )
            default_db = check_default_db()
            system["default_database"] = (
                "available" if default_db.get("ok") is True
                else "not_configured" if default_db.get("configured") is False
                else "unavailable"
            )
            shared_store = check_shared_store()
            system["shared_store"] = (
                "available" if shared_store.get("ok") else "degraded"
            )
        except (ImportError, AttributeError, OSError):
            system["dependency_checks"] = "unavailable"
        return {
            "users_total": users_total,
            "users_new_7d": users_new_7d,
            "analyses_total": analyses_total,
            "analyses_7d": int(activity["analyses_7d"] or 0),
            "active_users_7d": int(active_users or 0),
            "last_activity": activity["last_activity"],
            "logins_total": int(logins["total"] or 0),
            "logins_7d": int(logins["last_7d"] or 0),
            "page_visits_total": int(visits["total"] or 0),
            "page_visits_7d": int(visits["last_7d"] or 0),
            "page_visits_by_page": [
                {
                    "page": row["page"],
                    "total": int(row["total"] or 0),
                    "last_7d": int(row["last_7d"] or 0),
                }
                for row in page_visits
            ],
            "recent_events": [
                {
                    "event_type": row["event_type"],
                    "page": row["page"],
                    "occurred_at": row["occurred_at"],
                }
                for row in recent_events
            ],
            "system": system,
        }
    finally:
        conn.close()


def issue_token(user_id: int, username: str, ttl_hours: float | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "jti": secrets.token_hex(16),
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(hours=float(ttl_hours) if ttl_hours is not None
                               else TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, _signing_secret(), algorithm=JWT_ALGO)


# In-memory revocation cache: verify_token runs on EVERY request; without a
# cache each check pays a fresh SQLite connection + query. Entries are
# (expires_at_monotonic, revoked_bool). All revocations go through
# revoke_token, which writes through to the cache, so negatives stay
# consistent in-process; cross-process revocation lag is bounded by TTL.
_REVOKE_CACHE_TTL_SECONDS = 15.0
_REVOKE_CACHE: dict[str, tuple] = {}
_REVOKE_CACHE_LOCK = threading.Lock()

def _token_revoked_cached(token_hash: str) -> bool | None:
    now = time.monotonic()
    with _REVOKE_CACHE_LOCK:
        cached = _REVOKE_CACHE.get(token_hash)
        if cached is not None and now < cached[0]:
            return cached[1]
        if len(_REVOKE_CACHE) > 10_000:
            _REVOKE_CACHE.clear()
    return _token_revoked_db(token_hash)

def _token_revoked_db(token_hash: str) -> bool | None:
    """Return revocation state, or None when the store is unavailable.

    Store failures are deliberately not cached: callers fail closed for this
    request, while a recovered database can be checked again immediately.
    """
    try:
        conn = _get_db()
        try:
            revoked = conn.execute(
                "SELECT 1 FROM revoked_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return None
    with _REVOKE_CACHE_LOCK:
        _REVOKE_CACHE[token_hash] = (
            time.monotonic() + _REVOKE_CACHE_TTL_SECONDS, revoked,
        )
    return revoked


def verify_token(token: str) -> dict | None:
    try:
        if not token or not isinstance(token, str):
            return None
        payload = _decode_token(token)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        # Only a successful negative DB lookup authorizes this token. A store
        # outage must never be interpreted as "not revoked".
        if _token_revoked_cached(token_hash) is not False:
            return None
        # Strict `sub` validation: accept only a positive int user id or a
        # digit string (never bool/float/None/injection strings). int(True)
        # == 1 and int(3.5) == 3 would otherwise alias to another user.
        sub = payload.get("sub")
        if isinstance(sub, bool):
            return None
        if isinstance(sub, int):
            user_id = sub
        elif isinstance(sub, str) and sub.strip().isdigit():
            user_id = int(sub.strip())
        else:
            return None
        if user_id <= 0:
            return None
        return {"user_id": user_id, "username": payload.get("username")}
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


def revoke_token(token: str) -> None:
    """Invalidate this JWT until its own expiry without storing the token itself."""
    try:
        payload = _decode_token(token)
        if isinstance(payload, dict) and payload.get("exp") is None:
            return
        expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc).isoformat()
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return
    conn = _get_db()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM revoked_tokens WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT OR REPLACE INTO revoked_tokens (token_hash, expires_at) VALUES (?, ?)",
            (token_hash, expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    # Write-through so an immediately-following verify_token sees the
    # revocation even though the DB positive entry is now cached.
    with _REVOKE_CACHE_LOCK:
        _REVOKE_CACHE[token_hash] = (
            time.monotonic() + _REVOKE_CACHE_TTL_SECONDS, True,
        )


def add_history(user_id: int, *, goal: str, sql_used=None, row_count=None,
                columns=None, source_type=None, db_name=None, dialect=None,
                processed=None) -> int:
    conn = _get_db()
    try:
        cur = conn.execute(
            """INSERT INTO history
               (user_id, goal, sql_used, row_count, columns, source_type, db_name, dialect, processed_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, goal, sql_used, row_count,
                json.dumps(columns) if columns else None,
                source_type, db_name, dialect,
                json.dumps(processed) if processed is not None else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def set_history_insights(history_id: int, user_id: int, insights) -> None:
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE history SET insights_json = ? WHERE id = ? AND user_id = ?",
            (json.dumps(insights), history_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_history(user_id: int, limit: int = 200) -> list[dict]:
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT id, goal, sql_used, row_count, columns, source_type, db_name, dialect, created_at, insights_json
               FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "goal": r["goal"],
                "sql_used": r["sql_used"],
                "row_count": r["row_count"],
                "columns": json.loads(r["columns"]) if r["columns"] else [],
                "source_type": r["source_type"],
                "db_name": r["db_name"],
                "dialect": r["dialect"],
                "created_at": r["created_at"],
                "has_insights": bool(r["insights_json"]),
            }
        )
    return items


def get_history(user_id: int, history_id: int) -> dict | None:
    conn = _get_db()
    try:
        r = conn.execute(
            "SELECT * FROM history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    if not r:
        return None
    return {
        "id": r["id"],
        "goal": r["goal"],
        "sql_used": r["sql_used"],
        "row_count": r["row_count"],
        "columns": json.loads(r["columns"]) if r["columns"] else [],
        "source_type": r["source_type"],
        "db_name": r["db_name"],
        "dialect": r["dialect"],
        "created_at": r["created_at"],
        "processed": json.loads(r["processed_json"]) if r["processed_json"] else None,
        "insights": json.loads(r["insights_json"]) if r["insights_json"] else None,
    }


def delete_history(user_id: int, history_id: int) -> bool:
    conn = _get_db()
    try:
        cur = conn.execute(
            "DELETE FROM history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
