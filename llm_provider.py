"""
ARIA LLM Provider
-----------------
Unified interface over three LLM backends so the agents can run either:

  * local         - Ollama (offline, private, data never leaves the machine)  [SLOW]
  * cloud         - Groq API (fast, hosted inference)                          [FAST]
  * openai_compat - any OpenAI-compatible endpoint (Cerebras, Gemini, OpenRouter,
                    Together, SambaNova, ...) via its base URL + API key.       [FAST]

Every agent talks to `chat()` and never needs to know which backend it is.

Privacy context shown to the user:
    local: slow but your data stays on your machine (fully secure/offline)
    cloud: fast, but your schema/queries are sent to the Groq API
    openai_compat: fast, but your schema/queries are sent to the configured endpoint
"""

import logging
import os
import time
from urllib.parse import quote_plus

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

PROVIDERS = {
    "local": {
        "label": "Local LLM (Ollama)",
        "privacy": "Your data never leaves your machine. Fully offline & secure, but slower on commodity hardware.",
        "models": {
            "sql": "aria-sql-mistral",
            "story": "aria-story-mistral",
            "suggest": "aria-goal",
            "semi": "aria-goal",
        },
    },
    "cloud": {
        "label": "Cloud LLM (Groq API)",
        "privacy": "Fast inference on Groq's LPU hardware, but your schema, queries and data samples are sent to the Groq API.",
        "models": {
            "sql": "llama-3.3-70b-versatile",
            "story": "llama-3.3-70b-versatile",
            "suggest": "llama-3.3-70b-versatile",
            "semi": "llama-3.3-70b-versatile",
            "vision": "qwen/qwen3.6-27b",
        },
    },
    "openai_compat": {
        "label": "OpenAI-Compatible API",
        "privacy": "Fast hosted inference on the endpoint you configure (Cerebras, Gemini, OpenRouter, Together, SambaNova, ...). Your schema, queries and data samples are sent to that endpoint.",
        "models": {
            "sql": "llama-3.3-70b",
            "story": "llama-3.3-70b",
            "suggest": "llama-3.3-70b",
            "semi": "llama-3.3-70b",
        },
    },
}

GROQ_MODEL = PROVIDERS["cloud"]["models"]["sql"]

# ---------------------------------------------------------------------------
# OpenAI-compatible endpoint defaults (override via environment)
# ---------------------------------------------------------------------------
#  Cerebras:   base_url https://api.cerebras.ai/v1   models llama-3.3-70b
#  Gemini:     base_url https://generativelanguage.googleapis.com/v1beta/openai
#              models gemini-2.5-flash
#  OpenRouter: base_url https://openrouter.ai/api/v1 models deepseek/deepseek-chat:free
#  Together:   base_url https://api.together.xyz/v1   models meta-llama/...-instruct
#  SambaNova:  base_url https://api.sambanova.ai/v1   models Llama-3.3-70B-Instruct
OPENAI_COMPAT_BASE_URL = os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.cerebras.ai/v1")
OPENAI_COMPAT_API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "")
OPENAI_COMPAT_VISION_MODEL = os.getenv("OPENAI_COMPAT_VISION_MODEL", "")

# ---------------------------------------------------------------------------
# Gemini fallback for the Groq cloud backend
# ---------------------------------------------------------------------------
# When the Groq free tier hits its daily token limit (429), the session is NOT
# left dead: if a Gemini API key is configured, requests automatically fall back
# to Gemini (served through its OpenAI-compatible endpoint). Optional models:
#   GEMINI_SQL_MODEL / GEMINI_STORY_MODEL / GEMINI_SUGGEST_MODEL / GEMINI_SEMI_MODEL
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
GEMINI_MODELS = {
    "sql": os.getenv("GEMINI_SQL_MODEL", "gemini-2.5-flash"),
    "story": os.getenv("GEMINI_STORY_MODEL", "gemini-2.5-flash"),
    "suggest": os.getenv("GEMINI_SUGGEST_MODEL", "gemini-2.5-flash"),
    "semi": os.getenv("GEMINI_SEMI_MODEL", "gemini-2.5-flash"),
}

for _role in ("sql", "story", "suggest", "semi", "vision"):
    _env = os.getenv(f"OPENAI_COMPAT_{_role.upper()}_MODEL")
    if _env:
        PROVIDERS["openai_compat"]["models"][_role] = _env
del _role, _env


class LLMProvider:
    """Unified chat interface: local (Ollama) or cloud (Groq)."""

    def __init__(self, provider="local", api_key=None, models=None, base_url=None):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'. Choose from {list(PROVIDERS)}")
        self.provider = provider
        self.models = dict(PROVIDERS[provider]["models"])
        if models:
            self.models.update(models)

        self._groq_client = None
        self._openai_headers = None
        self._openai_base_url = None
        self._fallback = None  # optional secondary provider used on 429 rate limits
        if provider == "cloud":
            if not GROQ_AVAILABLE:
                raise RuntimeError("groq package is not installed. Run: pip install groq")
            # max_retries=0: the SDK's internal retry/backoff on 429s can block for
            # minutes. We handle rate limits ourselves with a short, bounded retry.
            self._groq_client = Groq(api_key=api_key or os.getenv("GROQ_API_KEY"), max_retries=0)
            if not self._groq_client.api_key:
                raise RuntimeError("Missing GROQ_API_KEY. Set it in .env or pass api_key.")
        elif provider == "openai_compat":
            if not HTTPX_AVAILABLE:
                raise RuntimeError("httpx package is not installed. Run: pip install httpx")
            key = api_key or OPENAI_COMPAT_API_KEY
            if not key:
                raise RuntimeError(
                    "Missing OPENAI_COMPAT_API_KEY. Set it in .env or pass api_key."
                )
            self._openai_base_url = (base_url or OPENAI_COMPAT_BASE_URL).rstrip("/")
            self._openai_headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }

    # -- model lookup ---------------------------------------------------

    def model_for(self, role):
        return self.models.get(role)

    @staticmethod
    def _is_rate_limit(exc):
        """True if the exception represents an HTTP 429 rate limit (from either
        the Groq SDK or httpx)."""
        status = getattr(exc, "status_code", None)
        if status is None:
            resp = getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
        return status == 429

    # -- unified chat ---------------------------------------------------

    def chat(self, role, messages, temperature=0.1, num_predict=400, timeout=None):
        """Send messages to the active backend for a given role (sql/story/suggest/semi).

        `timeout` is in seconds. If the call exceeds it, a TimeoutError is raised so
        the caller can fall back to a fast template instead of waiting indefinitely.
        Defaults: 30s for cloud, 60s for local (fast 1.5B coder on CPU).
        """
        if timeout is None:
            if self.provider == "local" and role in ("story", "prescription"):
                # Slow local model on CPU: generous default, but an explicit
                # timeout passed by the caller always wins (no hidden hang).
                timeout = 900
            else:
                timeout = 30 if self.provider != "local" else 60
        model = self.model_for(role)
        if not model:
            raise ValueError(f"No model configured for role '{role}'")

        try:
            if self.provider == "local":
                return self._chat_local(model, messages, temperature, num_predict, timeout)
            if self.provider == "openai_compat":
                return self._chat_openai(model, messages, temperature, num_predict, timeout)
            return self._chat_cloud(model, messages, temperature, num_predict, timeout)
        except TimeoutError:
            raise
        except Exception as exc:
            if self._is_rate_limit(exc) and self._fallback is not None:
                logging.warning(
                    f"Rate-limited on {self.provider}; falling back to {self._fallback.provider} "
                    f"for role '{role}'."
                )
                return self._fallback.chat(
                    role, messages, temperature=temperature,
                    num_predict=num_predict, timeout=timeout,
                )
            logging.warning(f"LLMProvider.{self.provider} chat failed ({role}): {exc}")
            raise

    def complete(self, role, prompt, temperature=0.1, num_predict=400, timeout=None):
        """Generate a raw completion for `prompt`.

        Used for completion-only models (e.g. sqlcoder locally, which has no chat
        template and just echoes the prompt when driven through `chat()`). For the
        cloud backend the prompt is sent as a single user message.
        """
        if timeout is None:
            if self.provider == "local" and role == "sql":
                timeout = 900
            else:
                timeout = 30 if self.provider != "local" else 300
        model = self.model_for(role)
        if not model:
            raise ValueError(f"No model configured for role '{role}'")

        try:
            if self.provider == "local":
                return self._complete_local(model, prompt, temperature, num_predict, timeout)
            if self.provider == "openai_compat":
                return self._complete_openai(model, prompt, temperature, num_predict, timeout)
            completion = self._cloud_with_retry(
                lambda: self._groq_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=num_predict,
                    timeout=timeout,
                )
            )
            return completion.choices[0].message.content.strip()
        except TimeoutError:
            raise
        except Exception as exc:
            if self._is_rate_limit(exc) and self._fallback is not None:
                logging.warning(
                    f"Rate-limited on {self.provider}; falling back to {self._fallback.provider} "
                    f"for role '{role}'."
                )
                return self._fallback.complete(
                    role, prompt, temperature=temperature,
                    num_predict=num_predict, timeout=timeout,
                )
            logging.warning(f"LLMProvider.{self.provider} complete failed ({role}): {exc}")
            raise

    def _complete_local(self, model, prompt, temperature, num_predict, timeout):
        if not OLLAMA_AVAILABLE:
            raise RuntimeError("ollama package is not installed. Run: pip install ollama")
        client = ollama.Client(timeout=timeout)
        response = client.generate(
            model=model,
            prompt=prompt,
            keep_alive="30m",
            options={
                "temperature": temperature,
                "num_predict": num_predict,
                "stop": ["<|im_end|>", "<|im_start|>", "```", "<|endoftext|>", "\n\nUser:"],
            },
        )
        return response["response"].strip()

    def _chat_local(self, model, messages, temperature, num_predict, timeout):
        if not OLLAMA_AVAILABLE:
            raise RuntimeError("ollama package is not installed. Run: pip install ollama")
        client = ollama.Client(timeout=timeout)
        response = client.chat(
            model=model,
            messages=messages,
            keep_alive="30m",
            options={"temperature": temperature, "num_predict": num_predict},
        )
        return response["message"]["content"].strip()

    def _chat_cloud(self, model, messages, temperature, num_predict, timeout):
        completion = self._cloud_with_retry(
            lambda: self._groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=num_predict,
                timeout=timeout,
            )
        )
        return completion.choices[0].message.content.strip()

    def _chat_openai(self, model, messages, temperature, num_predict, timeout):
        """OpenAI-compatible chat completion via httpx (no SDK required)."""
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": num_predict,
        }
        if model.startswith("qwen/"):
            data["response_format"] = {"type": "json_object"}
        response = self._cloud_with_retry(
            lambda: httpx.post(
                f"{self._openai_base_url}/chat/completions",
                headers=self._openai_headers,
                json=data,
                timeout=timeout,
            )
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def _complete_openai(self, model, prompt, temperature, num_predict, timeout):
        """OpenAI-compatible single-message completion."""
        return self._chat_openai(
            model, [{"role": "user", "content": prompt}],
            temperature, num_predict, timeout,
        )

    def _cloud_with_retry(self, fn, attempts=3):
        """Call `fn` (a Groq or OpenAI-compatible request) with a bounded retry
        for rate limits.

        Both clients are configured/used with retries disabled so a 429 never
        blocks on the SDK's own long retry-after backoff. Here we wait only a
        short, capped delay and give up after a few attempts, raising the last
        error so callers fall back to templates instead of hanging on the request.
        """
        last_exc = None
        for attempt in range(attempts):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                response = getattr(exc, "response", None)
                status = getattr(exc, "status_code", None)
                if status is None and response is not None:
                    status = getattr(response, "status_code", None)
                if status != 429 or attempt >= attempts - 1:
                    raise
                wait = 1.5
                try:
                    retry_after = float(response.headers.get("retry-after", 0))  # type: ignore[union-attr]
                    if retry_after > 0:
                        wait = min(retry_after, 5.0)
                except Exception:
                    pass
                logging.warning("Rate limit (429); retrying in %.1fs (attempt %d/%d)",
                                wait, attempt + 1, attempts)
                time.sleep(wait)
        raise last_exc  # pragma: no cover

    def vision(self, prompt, images, temperature=0.1, num_predict=1500, timeout=60):
        """Send rendered page images (base64 PNG strings) plus a text prompt to a
        vision model. Available on the cloud (Groq) backend and any openai_compat
        endpoint configured with a vision model.

        Used to transcribe scanned/handwritten PDFs into structured records.
        """
        model = self.models.get("vision")
        if not model:
            raise RuntimeError(f"No vision model configured for provider '{self.provider}'.")
        if self.provider == "local":
            raise RuntimeError(
                "Handwritten/scanned PDF extraction requires a hosted provider "
                "(Groq or an OpenAI-compatible endpoint with a vision model). "
                "Switch backend and retry."
            )
        content = [{"type": "text", "text": prompt}]
        for b64 in images:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        try:
            return self._vision_once(prompt, images, content, model, temperature, num_predict, timeout)
        except TimeoutError:
            raise
        except Exception as exc:
            if self._is_rate_limit(exc) and self._fallback is not None:
                logging.warning(
                    f"Rate-limited on {self.provider}; falling back to {self._fallback.provider} for vision."
                )
                return self._fallback.vision(
                    prompt, images, temperature=temperature,
                    num_predict=num_predict, timeout=timeout,
                )
            raise

    def _vision_once(self, prompt, images, content, model, temperature, num_predict, timeout):
        if self.provider == "openai_compat":
            data = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
                "max_tokens": num_predict,
            }
            if model.startswith("qwen/"):
                data["response_format"] = {"type": "json_object"}
            response = self._cloud_with_retry(
                lambda: httpx.post(
                    f"{self._openai_base_url}/chat/completions",
                    headers=self._openai_headers,
                    json=data,
                    timeout=timeout,
                )
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        kwargs = {}
        if model.startswith("qwen/"):
            kwargs["response_format"] = {"type": "json_object"}
        completion = self._cloud_with_retry(
            lambda: self._groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=temperature,
                max_tokens=num_predict,
                timeout=timeout,
                **kwargs,
            )
        )
        return completion.choices[0].message.content.strip()

    def __repr__(self):
        return f"LLMProvider(provider={self.provider}, models={self.models})"


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def create_provider(provider="local", api_key=None, models=None, base_url=None):
    """Build an LLMProvider.

    Policy: never silently switch backend. If a hosted provider ('cloud' or
    'openai_compat') is requested but its dependencies/key are missing, raise so
    the caller/user decides (no silent downgrade to local). Switching provider
    mid-session only happens through an explicit user action (see
    /api/provider/switch) — never automatically.
    """
    if provider == "cloud":
        if not GROQ_AVAILABLE:
            raise RuntimeError(
                "The Cloud provider is unavailable because the 'groq' package is not "
                "installed (pip install groq). Stay on Local or fix this first."
            )
        llm = LLMProvider("cloud", api_key=api_key or os.getenv("GROQ_API_KEY"), models=models)
        if not llm._groq_client.api_key:
            raise RuntimeError("Missing GROQ_API_KEY. Set it in .env or pass api_key.")
        # Automatic rate-limit fallback: when the Groq free tier is exhausted
        # (429), retry the same request on Gemini via its OpenAI-compatible
        # endpoint, if a Gemini key is configured. Never silently downgrades to
        # Local — both are hosted backends the user has opted into.
        if GEMINI_API_KEY:
            try:
                llm._fallback = LLMProvider(
                    "openai_compat",
                    api_key=GEMINI_API_KEY,
                    base_url=GEMINI_BASE_URL,
                    models=GEMINI_MODELS,
                )
            except Exception as exc:
                logging.warning(f"Gemini fallback could not be initialised: {exc}")
        return llm
    if provider == "openai_compat":
        llm = LLMProvider(
            "openai_compat",
            api_key=api_key or os.getenv("OPENAI_COMPAT_API_KEY"),
            models=models,
            base_url=base_url or os.getenv("OPENAI_COMPAT_BASE_URL"),
        )
        return llm
    return LLMProvider("local", models=models)
