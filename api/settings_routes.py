"""Settings routes: AI provider configuration and general settings."""

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.config import get_session, save_session
from core.deps import get_current_user
from llm_provider import PROVIDERS, create_provider

router = APIRouter()

log = logging.getLogger("aria.settings")

# UI-facing names mapped to real backend providers. Anything else is
# rejected with the supported list (no silent misconfiguration).
PROVIDER_ALIASES = {
    "local": "local",
    "ollama": "local",
    "cloud": "cloud",
    "groq": "cloud",
    "deepseek": "deepseek",
    "omniroute": "omniroute",
    "universal": "omniroute",
    "grok": "grok",
    "xai": "grok",
    "x-ai": "grok",
}


class ProviderConfigRequest(BaseModel):
    provider: str
    api_key: str
    is_default: bool = False


class GeneralSettingsRequest(BaseModel):
    language: str = "en"
    theme: str = "light"


@router.get("/api/settings/providers")
async def get_providers(_user: dict = Depends(get_current_user)):
    """List configured AI providers."""
    session = get_session(_user["user_id"])
    configured = session.get("configured_providers", [])
    providers = []
    for p in configured:
        providers.append({
            "name": PROVIDERS.get(p, {}).get("label", p),
            "provider": p,
            "is_default": p == session.get("provider_name", "local"),
        })
    return {"ok": True, "providers": providers}


@router.post("/api/settings/providers")
async def save_provider(req: ProviderConfigRequest, _user: dict = Depends(get_current_user)):
    """Save an AI provider API key AND switch the session to it.

    The key is validated with a tiny bounded call first, so a typo'd key
    fails here with a clear message instead of breaking later analyses.
    """
    raw = (req.provider or "").strip().lower()
    name = PROVIDER_ALIASES.get(raw)
    if not name:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{req.provider}'. Choose from: local, cloud, deepseek, omniroute, grok.",
        )
    key = (req.api_key or "").strip()
    if name != "local" and not key:
        raise HTTPException(status_code=400, detail=f"An API key is required for '{name}'.")

    # Validate the key with a minimal bounded call before storing anything.
    try:
        llm = create_provider(provider=name, api_key=key or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{name}': {exc}")
    if name != "local":
        try:
            await asyncio.to_thread(llm.ping, 25)
        except Exception as exc:
            log.warning("Provider key validation failed for '%s': %s", name, exc)
            raise HTTPException(
                status_code=400,
                detail=f"The {name} key was rejected or unreachable ({exc}). Check the key and try again.",
            )

    session = get_session(_user["user_id"])
    configured = session.get("configured_providers", [])
    if name not in configured:
        configured.append(name)
    session["configured_providers"] = configured
    session["provider_name"] = name
    session["provider"] = llm
    if key:
        keys = session.get("api_keys", {})
        keys[name] = key
        session["api_keys"] = keys
    save_session(_user["user_id"], session)
    return {"ok": True, "provider": name, "message": f"Provider '{name}' verified and activated"}


@router.get("/api/settings/models")
async def get_models(_user: dict = Depends(get_current_user)):
    """List available AI models from configured providers."""
    models = []
    for provider_name, provider_meta in PROVIDERS.items():
        for model_key, model_id in provider_meta.get("models", {}).items():
            models.append({
                "id": f"{provider_name}/{model_key}",
                "name": f"{provider_meta['label']} - {model_key}",
                "provider": provider_name,
                "model_id": model_id,
            })
    return {"ok": True, "models": models}


@router.get("/api/providers/status")
async def providers_status(_user: dict = Depends(get_current_user)):
    """Live availability per provider for the LLM selection screen (§5).

    Local: Ollama reachable (fast tag check, no generation). Cloud/hosted:
    key configured (saved or env) AND provider reachable. Never raises —
    unreachable providers report available=false with a reason.
    """
    import asyncio as _asyncio

    from core.config import resolve_provider_key

    session = get_session(_user["user_id"])
    saved = session.get("api_keys", {}) if isinstance(session.get("api_keys"), dict) else {}

    async def _check(name: str) -> dict:
        if name == "local":
            try:
                await _asyncio.to_thread(_ping_ollama, 5)
                return {"provider": name, "available": True, "reason": "Ollama is running on this machine."}
            except Exception as exc:
                return {"provider": name, "available": False,
                        "reason": f"Ollama is not reachable ({exc}). Start Ollama and try again."}
        key = resolve_provider_key(name, saved)
        if not key:
            label = {"cloud": "Groq", "deepseek": "DeepSeek", "omniroute": "OmniRoute", "grok": "Grok"}.get(name, name)
            return {"provider": name, "available": False,
                    "reason": f"No {label} API key saved. Add one to use {label}."}
        try:
            await _asyncio.to_thread(_ping_hosted, name, key, 8)
            return {"provider": name, "available": True, "reason": "API key verified and reachable."}
        except Exception as exc:
            return {"provider": name, "available": False,
                    "reason": f"Key rejected or unreachable ({exc}). Check the key and retry."}

    names = ["local", "cloud", "deepseek", "omniroute", "grok"]
    results = await _asyncio.gather(*[_check(n) for n in names])
    return {"ok": True, "providers": results,
            "active": session.get("provider_name")}


def _ping_ollama(timeout: int) -> None:
    """Fast Ollama liveness check (tags endpoint, no generation)."""
    import urllib.request as _url
    import json as _json
    base = (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
    req = _url.Request(f"{base}/api/tags", method="GET")
    with _url.urlopen(req, timeout=timeout) as resp:
        payload = _json.loads(resp.read().decode("utf-8") or "{}")
    models = {str(m.get("name", "")).split(":")[0]
              for m in (payload.get("models") or []) if isinstance(m, dict)}
    needed = {"aria-sql-mistral", "aria-story-mistral", "aria-goal"}
    if models and needed.isdisjoint(models):
        raise RuntimeError("Ollama runs but none of the ARIA models are installed.")


def _ping_hosted(name: str, key: str, timeout: int) -> None:
    """Verify a hosted provider key with a no-cost models.list call."""
    from llm_provider import create_provider
    llm = create_provider(provider=name, api_key=key)
    llm.ping(timeout=timeout)


@router.post("/api/settings/general")
async def save_general_settings(req: GeneralSettingsRequest, _user: dict = Depends(get_current_user)):
    """Save general settings (theme, language)."""
    if req.language not in {"en", "ur"}:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    if req.theme not in {"light", "dark", "system"}:
        raise HTTPException(status_code=400, detail="Unsupported theme.")
    session = get_session(_user["user_id"])
    session["settings"] = {
        "language": req.language,
        "theme": req.theme,
    }
    save_session(_user["user_id"], session)
    return {"ok": True, "message": "Settings saved"}
