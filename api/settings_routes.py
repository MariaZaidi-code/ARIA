"""Settings routes: AI provider configuration and general settings."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core.config import get_session
from core.deps import get_current_user
from llm_provider import PROVIDERS

router = APIRouter()


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
    """Save an AI provider API key."""
    session = get_session(_user["user_id"])
    configured = session.get("configured_providers", [])
    if req.provider not in configured:
        configured.append(req.provider)
    session["configured_providers"] = configured
    if req.is_default:
        session["provider_name"] = req.provider
    # Store user-provided API key per provider (encrypted at rest via DPAPI if needed)
    keys = session.get("api_keys", {})
    keys[req.provider] = req.api_key
    session["api_keys"] = keys
    return {"ok": True, "message": f"Provider '{req.provider}' saved"}


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


@router.post("/api/settings/general")
async def save_general_settings(req: GeneralSettingsRequest, _user: dict = Depends(get_current_user)):
    """Save general settings (theme, language)."""
    session = get_session(_user["user_id"])
    session["settings"] = {
        "language": req.language,
        "theme": req.theme,
    }
    return {"ok": True, "message": "Settings saved"}
