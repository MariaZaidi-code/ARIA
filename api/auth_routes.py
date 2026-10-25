"""Authentication and per-user history routes."""

import os
import smtplib
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, BaseModel

import auth
from core.deps import get_current_user, is_mobile, require_admin, require_writable

router = APIRouter()

COOKIE_NAME = "aria_token"
SECURE_COOKIE_NAME = "__Host-aria_token"


def _is_loopback_http(request: Request | None = None) -> bool:
    """Return true only for local plain-HTTP development origins.

    Browsers reject Secure cookies over ordinary HTTP. Restrict the local
    development exception to explicit loopback hosts so a proxied/public
    deployment continues to use Secure cookies.
    """
    if request is None:
        return False
    try:
        host = (request.url.hostname or "").strip("[]").lower()
        return request.url.scheme.lower() == "http" and host in {
            "localhost", "127.0.0.1", "::1",
        }
    except Exception:
        return False


def _cookie_secure(request: Request | None = None) -> bool:
    """Secure flag for the auth cookie. Default True (prod-safe).

    Plain HTTP on a loopback host uses a non-Secure cookie because browsers
    discard Secure cookies there. Elsewhere, ARIA_COOKIE_SECURE or
    ARIA_ENV=dev/development/local may opt out; any other/unset value stays
    Secure so production does not accidentally weaken cookie transport.
    """
    explicit = (os.getenv("ARIA_COOKIE_SECURE") or "").strip().lower()
    if explicit in ("0", "false", "no", "off"):
        return False
    # Local ARIA is commonly opened at http://127.0.0.1:8000. Even if a
    # machine-level environment variable was inherited by the server,
    # issuing a Secure cookie on this plain-HTTP loopback origin makes the
    # browser discard the session and causes protected actions to appear to
    # log the user out. Loopback HTTP must use the plain cookie name; public
    # hosts and HTTPS loopback remain Secure.
    if _is_loopback_http(request):
        return False
    if explicit in ("1", "true", "yes", "on"):
        return True
    if (os.getenv("ARIA_ENV") or "").strip().lower() in ("dev", "development", "local"):
        return False
    return True


def _cookie_name(request: Request | None = None) -> str:
    # __Host- prefix requires Secure, Path=/, and no Domain — all true
    # when secure. Use plain name for explicit local-HTTP dev.
    return SECURE_COOKIE_NAME if _cookie_secure(request) else COOKIE_NAME


def _cookie_kwargs(request: Request | None = None) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": _cookie_secure(request),
        "path": "/",
        "max_age": auth.TOKEN_TTL_HOURS * 3600,
    }


def _auth_response(
    token: str,
    username: str,
    request: Request | None = None,
    user_id: int | None = None,
) -> JSONResponse:
    # HttpOnly cookie flow: never return the raw JWT in JSON.
    resp = JSONResponse({
        "ok": True,
        "username": username,
        "email": username,
        "user_id": user_id,
        "is_admin": auth.is_admin_email(username),
    })
    cookie_name = _cookie_name(request)
    cookie_kwargs = _cookie_kwargs(request)
    resp.set_cookie(cookie_name, token, **cookie_kwargs)
    # Remove a cookie issued under the other scheme when a client moves
    # between HTTPS and local HTTP; otherwise an old token can shadow the new
    # session in clients that choose the first cookie by name.
    stale_cookie = SECURE_COOKIE_NAME if cookie_name == COOKIE_NAME else COOKIE_NAME
    resp.delete_cookie(
        stale_cookie,
        path="/",
        secure=stale_cookie == SECURE_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )
    return resp

# Brute-force guard: sliding-window per client IP (generous so real users
# and E2E never trip it; only credential-stuffing bursts get 429).
# Storage model (P0-3): in-memory per-process, LOCAL/DEV ONLY. Multi-worker
# production must set ARIA_REDIS_URL + ARIA_REQUIRE_SHARED_STORE=1 (see
# core/ratelimit._check_shared_store); otherwise each worker enforces its
# own per-process login budget.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCK = threading.Lock()
_LOGIN_WINDOW_S = 300
_LOGIN_MAX = 30
# Bound for the per-process login map: prune entries idle past the window
# and cap distinct IPs so a long-running server cannot grow unbounded.
_LOGIN_MAX_IPS = 10_000
_LOGIN_LAST_PRUNE: float = 0.0


def _prune_login_attempts(now: float | None = None) -> int:
    """Expire stale login entries and enforce the IP cap. Returns removed IPs.

    Drops per-IP timestamps older than _LOGIN_WINDOW_S, removes empty IPs,
    then evicts oldest-last-seen IPs while over _LOGIN_MAX_IPS. Never raises.
    """
    global _LOGIN_LAST_PRUNE
    try:
        current = float(now) if now is not None else time.monotonic()
        removed = 0
        for ip in list(_LOGIN_ATTEMPTS.keys()):
            try:
                hits = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if current - t < _LOGIN_WINDOW_S]
            except Exception:
                hits = []
            if hits:
                _LOGIN_ATTEMPTS[ip] = hits
            else:
                _LOGIN_ATTEMPTS.pop(ip, None)
                removed += 1
        if len(_LOGIN_ATTEMPTS) > _LOGIN_MAX_IPS:
            # Evict oldest-last-seen first (deterministic, bounded memory).
            try:
                ordered = sorted(
                    _LOGIN_ATTEMPTS.items(),
                    key=lambda kv: max(kv[1]) if kv[1] else 0.0,
                )
                excess = len(_LOGIN_ATTEMPTS) - _LOGIN_MAX_IPS
                for ip, _ in ordered[:excess]:
                    _LOGIN_ATTEMPTS.pop(ip, None)
                    removed += 1
            except Exception:
                while len(_LOGIN_ATTEMPTS) > _LOGIN_MAX_IPS:
                    _LOGIN_ATTEMPTS.pop(next(iter(_LOGIN_ATTEMPTS)), None)
                    removed += 1
        _LOGIN_LAST_PRUNE = current
        return removed
    except Exception:
        return 0


def _check_login_rate_limit(request: Request) -> None:
    now = time.monotonic()
    ip = request.client.host if request.client else "unknown"
    # Shared enforcement first (multi-worker): check_limit propagates the
    # shared 429/503 instead of splitting the budget across workers.
    from core.ratelimit import check_limit
    check_limit("login", ip, _LOGIN_MAX, _LOGIN_WINDOW_S)
    # Mutations on _LOGIN_ATTEMPTS must be atomic: the threadpool runs
    # concurrent requests, and read-filter-append loses attempts under load.
    with _LOGIN_LOCK:
        hits = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if now - t < _LOGIN_WINDOW_S]
        if len(hits) >= _LOGIN_MAX:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a few minutes.")
        hits.append(now)
        _LOGIN_ATTEMPTS[ip] = hits
        # Opportunistic global prune: cheap per-request for this IP is already
        # done above; run the full sweep periodically or when over the cap so
        # the map cannot grow unbounded across many distinct IPs.
        global _LOGIN_LAST_PRUNE
        if len(_LOGIN_ATTEMPTS) > _LOGIN_MAX_IPS or (now - _LOGIN_LAST_PRUNE) > 60:
            _prune_login_attempts(now)


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    email: str
    password: str


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    token: str


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    email: str


class PageVisitRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    page: str


@router.post("/api/auth/register")
def register(auth_req: AuthRequest, request: Request):
    """Create an account and send an email verification link."""
    _check_login_rate_limit(request)
    try:
        email = auth.normalize_email(auth_req.email)
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    try:
        user_id = auth.register_email(email, auth_req.password)
    except ValueError:
        # Do not disclose whether an email has an existing account.
        token = auth.create_email_verification_token(email)
        if token:
            try:
                auth.send_email_verification(email, token)
            except (OSError, RuntimeError, smtplib.SMTPException) as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Could not send the verification email. Check mail settings and try again.",
                ) from exc
        return {
            "ok": True,
            "verification_required": True,
            "message": "If this address can be registered, a verification link has been sent.",
        }
    token = auth.create_email_verification_token(email)
    if not token:
        raise HTTPException(status_code=500, detail="Could not create email verification.")
    try:
        auth.send_email_verification(email, token)
    except (OSError, RuntimeError, smtplib.SMTPException) as exc:
        # Dev fallback: when SMTP is not configured, verification email
        # cannot be delivered. Mark the account verified so local users can
        # still sign in; production deployments must configure SMTP.
        if isinstance(exc, RuntimeError) and "not configured" in str(exc).lower():
            auth.verify_email_token(token)
            return {
                "ok": True,
                "verification_required": False,
                "message": "Account created. You can now sign in.",
            }
        raise HTTPException(
            status_code=503,
            detail="Your account is pending verification, but the email could not be sent. Try resending after checking mail settings.",
        ) from exc
    return {
        "ok": True,
        "verification_required": True,
        "message": "Check your email for a verification link before signing in.",
    }


@router.post("/api/auth/login")
def login(auth_req: AuthRequest, request: Request):
    """Exchange a verified email/password pair for a JWT."""
    _check_login_rate_limit(request)
    account = auth.authenticate_email(auth_req.email, auth_req.password)
    if not account:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not account.get("verified"):
        raise HTTPException(
            status_code=403,
            detail="Verify your email address before signing in.",
        )
    email = account["email"]
    return _auth_response(
        auth.issue_token(account["user_id"], email),
        email,
        request,
        user_id=account["user_id"],
    )


@router.post("/api/auth/verify-email")
def verify_email(req: VerificationRequest):
    email = auth.verify_email_token(req.token)
    if not email:
        raise HTTPException(
            status_code=400,
            detail="This verification link is invalid, expired, or already used.",
        )
    return {"ok": True, "message": "Email verified. You can now sign in."}


@router.post("/api/auth/resend-verification")
def resend_verification(req: ResendVerificationRequest, request: Request):
    _check_login_rate_limit(request)
    try:
        email = auth.normalize_email(req.email)
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    token = auth.create_email_verification_token(email)
    if token:
        try:
            auth.send_email_verification(email, token)
        except (OSError, RuntimeError, smtplib.SMTPException) as exc:
            raise HTTPException(
                status_code=503,
                detail="Could not send the verification email. Check mail settings and try again.",
            ) from exc
    return {
        "ok": True,
        "message": "If this account needs verification, a new link has been sent.",
    }


@router.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    email = str(user.get("username") or "")
    return {
        "ok": True,
        "username": email,
        "email": email,
        "user_id": user["user_id"],
        "is_admin": auth.is_admin_email(email),
    }


@router.get("/api/admin/overview")
def admin_overview(user: dict = Depends(require_admin)):
    return {"ok": True, "overview": auth.get_admin_overview()}


@router.post("/api/admin/page-visit")
def admin_page_visit(
    req: PageVisitRequest, user: dict = Depends(get_current_user),
):
    allowed_pages = {
        "admin", "dashboard", "analytics", "insights", "intelligence",
        "predictive", "data", "documents", "copilot", "history", "settings",
    }
    page = (req.page or "").strip().lower()
    if page not in allowed_pages:
        raise HTTPException(status_code=400, detail="Unknown page.")
    auth.record_auth_event(user["user_id"], "page_visit", page)
    return {"ok": True}


@router.post("/api/auth/logout")
def logout(request: Request, user: dict = Depends(get_current_user)):
    """Revoke the presented JWT and acknowledge logout."""
    seen: set[str] = set()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        seen.add(authorization[7:].strip())
    # Revoke whichever cookie(s) the client presented (backward compat:
    # accept both __Host- prefixed and legacy plain names).
    for name in (SECURE_COOKIE_NAME, COOKIE_NAME):
        tok = request.cookies.get(name)
        if tok:
            seen.add(tok.strip())
    for tok in seen:
        if tok and tok.lower() not in ("null", "undefined", '""', "''"):
            auth.revoke_token(tok)
    resp = JSONResponse({"ok": True, "username": user["username"]})
    for name in (SECURE_COOKIE_NAME, COOKIE_NAME):
        resp.delete_cookie(name, path="/")
    return resp


@router.get("/api/history")
def history(request: Request, user: dict = Depends(get_current_user), limit: int = 200):
    """List the current user's saved analyses (metadata only, newest first)."""
    items = auth.list_history(user["user_id"], limit=max(1, min(limit, 500)))
    return {
        "ok": True,
        "mode": "read-only" if is_mobile(request) else "full",
        "items": items,
    }


@router.get("/api/history/{history_id}")
def history_detail(history_id: int, user: dict = Depends(get_current_user)):
    """Return one saved analysis including processed data and insights."""
    record = auth.get_history(user["user_id"], history_id)
    if not record:
        raise HTTPException(status_code=404, detail="History record not found.")
    return {"ok": True, "record": record}


@router.delete("/api/history/{history_id}")
def history_delete(history_id: int, user: dict = Depends(require_writable)):
    """Delete a saved analysis (blocked on mobile: view history only)."""
    deleted = auth.delete_history(user["user_id"], history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History record not found.")
    return {"ok": True}
