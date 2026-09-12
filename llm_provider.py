"""
ARIA LLM Provider
-----------------
Unified interface over two LLM backends so the agents can run either:

  * local  - Ollama (offline, private, data never leaves the machine)  [SLOW]
  * cloud  - Groq API (fast, hosted inference)                          [FAST]

Every agent talks to `chat()` and never needs to know which backend it is.

Privacy context shown to the user:
    local: slow but your data stays on your machine (fully secure/offline)
    cloud: fast, but your schema/queries are sent to the Groq API
"""

import json
import logging
import os
import re
import time
from urllib.parse import quote_plus

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

# Load .env centrally (in core.config) before any module-level os.getenv below.
import core.config  # noqa: E402,F401

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# DeepSeek (OpenAI-compatible) configuration
# ---------------------------------------------------------------------------

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_VISION_MODEL = os.getenv("DEEPSEEK_VISION_MODEL", DEEPSEEK_MODEL)
DEEPSEEK_THINKING = os.getenv("DEEPSEEK_THINKING", "disabled").strip().lower()
if DEEPSEEK_THINKING not in {"enabled", "disabled"}:
    DEEPSEEK_THINKING = "disabled"

# Control-plane RAG calls use tiny bounded outputs and must not spend that
# budget on hidden reasoning.
_CONTROL_ROLES = {"rag_scope", "rag_verify", "rag_rewrite", "rag_plan"}
_RETRY_AFTER_RE = re.compile(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)

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
            "schema": "aria-goal",
        },
    },
    "cloud": {
        "label": "Cloud LLM (Groq API)",
        "privacy": "Fast inference on Groq's LPU hardware, but your schema, queries and data samples are sent to the Groq API.",
        "models": {
            "sql": "openai/gpt-oss-120b",
            "story": "openai/gpt-oss-120b",
            "suggest": "openai/gpt-oss-120b",
            "semi": "openai/gpt-oss-120b",
            "schema": "openai/gpt-oss-120b",
            "vision": "qwen/qwen3.6-27b",
        },
    },
    "omniroute": {
        "label": "OmniRoute",
        "privacy": "Aggregated model routing; schema and queries are sent to the OmniRoute API.",
        "models": {
            "free-best": "omniroute/free-best",
            "free-fast": "omniroute/free-fast",
            "free-chat": "omniroute/free-chat",
            "open": "omniroute/open",
        },
    },
    "deepseek": {
        "label": "Cloud LLM (DeepSeek API)",
        "privacy": "Hosted DeepSeek inference. Your schema, queries, selected PDF evidence, and data samples may be sent to the DeepSeek API.",
        "models": {
            "sql": DEEPSEEK_MODEL,
            "story": DEEPSEEK_MODEL,
            "suggest": DEEPSEEK_MODEL,
            "semi": DEEPSEEK_MODEL,
            "schema": DEEPSEEK_MODEL,
            "vision": DEEPSEEK_VISION_MODEL,
        },
    },
}

GROQ_MODEL = PROVIDERS["cloud"]["models"]["sql"]

# Local Ollama models default to a small runtime context (often 4096 tokens),
# which the schema-reasoning prompt + long output can exceed. Raise it so large
# schemas are not rejected with an "exceeds the available context size" error.
LOCAL_NUM_CTX = 8192


class LLMProvider:
    """Unified chat interface: local (Ollama) or cloud (Groq)."""

    def __init__(self, provider="local", api_key=None, models=None, base_url=None):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'. Choose from {list(PROVIDERS)}")
        self.provider = provider
        self.base_url = base_url
        self.models = dict(PROVIDERS[provider]["models"])
        if models:
            self.models.update(models)

        # Unified cloud client used by all hosted providers (Groq "cloud" and
        # DeepSeek "deepseek"). Kept as a single attribute so every cloud path
        # shares the same retry/error handling.
        self._cloud_client = None
        if provider == "cloud":
            if not GROQ_AVAILABLE:
                raise RuntimeError("groq package is not installed. Run: pip install groq")
            # max_retries=0: the SDK's internal retry/backoff on 429s can block for
            # minutes. We handle rate limits ourselves with a short, bounded retry.
            self._cloud_client = Groq(api_key=api_key or os.getenv("GROQ_API_KEY"), max_retries=0, base_url=base_url) if base_url else Groq(api_key=api_key or os.getenv("GROQ_API_KEY"), max_retries=0)
            if not self._cloud_client.api_key:
                raise RuntimeError("Missing GROQ_API_KEY. Set it in .env or pass api_key.")
        elif provider == "deepseek":
            from openai import OpenAI
            self._cloud_client = OpenAI(
                api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
                base_url=base_url or DEEPSEEK_BASE_URL,
            )
            if not self._cloud_client.api_key:
                raise RuntimeError("Missing DEEPSEEK_API_KEY. Set it in .env or pass api_key.")

    # -- model lookup ---------------------------------------------------

    def model_for(self, role):
        return self.models.get(role)

    # -- thinking control ------------------------------------------------

    def _thinking_body(self, role=None):
        """Return provider-specific ``extra_body`` for reasoning control.

        DeepSeek accepts a ``thinking`` switch: control-plane RAG calls use tiny
        bounded outputs and must not spend that budget on hidden reasoning, so
        they always disable it. General DeepSeek generation follows the env
        switch. Groq does not accept this field, so it gets an empty body.
        """
        if self.provider != "deepseek":
            return {}
        thinking = "disabled" if role in _CONTROL_ROLES else DEEPSEEK_THINKING
        return {"thinking": {"type": thinking}}

    def chat_structured(
        self,
        role,
        messages,
        *,
        json_schema,
        schema_name="structured_response",
        temperature=0.0,
        num_predict=900,
        timeout=None,
        reasoning_effort="low",
    ):
        """Return JSON-mode content from the hosted provider as a raw string.

        DeepSeek and Groq both support ``response_format={type: json_object}``.
        ARIA still performs its own Pydantic/schema validation afterwards, so
        provider JSON mode is a formatting hint, never a trust boundary.
        The JSON Schema is injected as a system instruction that the caller's
        own validation enforces.
        """
        del reasoning_effort  # accepted for interface compatibility
        if self.provider == "local":
            raise RuntimeError("Structured output is available only on a hosted provider.")
        if timeout is None:
            timeout = 20
        model = self.model_for(role)
        if not model:
            raise ValueError(f"No model configured for role '{role}'")
        if not isinstance(json_schema, dict) or json_schema.get("type") != "object":
            raise ValueError("json_schema must be a JSON Schema object definition.")

        schema_text = json.dumps(json_schema, ensure_ascii=False, separators=(",", ":"))
        structured_messages = [
            {
                "role": "system",
                "content": (
                    f"Return only one valid JSON object named {schema_name}. "
                    "It must match this JSON Schema exactly. Do not use markdown fences, "
                    "commentary, or extra keys. "
                    f"JSON Schema: {schema_text}"
                ),
            },
            *messages,
        ]
        extra_body = self._thinking_body(role)
        try:
            def _request():
                kwargs = {
                    "model": model,
                    "messages": structured_messages,
                    "temperature": temperature,
                    "max_tokens": num_predict,
                    "timeout": timeout,
                    "response_format": {"type": "json_object"},
                }
                if extra_body:
                    kwargs["extra_body"] = extra_body
                return self._cloud_client.chat.completions.create(**kwargs)

            completion = self._cloud_with_retry(_request)
            content = completion.choices[0].message.content
            if not content:
                raise RuntimeError("Structured LLM response was empty.")
            return content.strip()
        except TimeoutError:
            raise
        except Exception as exc:
            logging.warning("LLMProvider.%s structured chat failed (%s): %s",
                            self.provider, role, exc)
            raise

    # -- unified chat ---------------------------------------------------

    def chat(self, role, messages, temperature=0.1, num_predict=400, timeout=None):
        """Send messages to the active backend for a given role (sql/story/suggest/semi).

        `timeout` is in seconds. If the call exceeds it, a TimeoutError is raised so
        the caller can fall back to a fast template instead of waiting indefinitely.
        Defaults: 30s for cloud, 60s for local (fast 1.5B coder on CPU).
        """
        if timeout is None:
            if self.provider == "local" and role in ("story",):
                # Slow local model on CPU: generous default, but an explicit
                # timeout passed by the caller always wins (no hidden hang).
                timeout = 900
            else:
                # Short, bounded timeouts so analytical queries respond quickly
                # rather than blocking indefinitely on a slow LLM response.
                timeout = 15 if self.provider != "local" else 30
        model = self.model_for(role)
        if not model:
            raise ValueError(f"No model configured for role '{role}'")

        try:
            if self.provider == "local":
                return self._chat_local(model, messages, temperature, num_predict, timeout)
            return self._chat_cloud(role, model, messages, temperature, num_predict, timeout)
        except TimeoutError:
            raise
        except Exception as exc:
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
            extra_body = self._thinking_body(role)
            def _request():
                kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": num_predict,
                    "timeout": timeout,
                }
                if extra_body:
                    kwargs["extra_body"] = extra_body
                return self._cloud_client.chat.completions.create(**kwargs)

            completion = self._cloud_with_retry(_request)
            content = completion.choices[0].message.content
            return (content or "").strip()
        except TimeoutError:
            raise
        except Exception as exc:
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
                "num_ctx": LOCAL_NUM_CTX,
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
            options={"temperature": temperature, "num_predict": num_predict, "num_ctx": LOCAL_NUM_CTX},
        )
        return response["message"]["content"].strip()

    def _chat_cloud(self, role, model, messages, temperature, num_predict, timeout):
        extra_body = self._thinking_body(role)
        def _request():
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": num_predict,
                "timeout": timeout,
            }
            if extra_body:
                kwargs["extra_body"] = extra_body
            return self._cloud_client.chat.completions.create(**kwargs)

        completion = self._cloud_with_retry(_request)
        content = completion.choices[0].message.content
        if not content:
            raise RuntimeError("Cloud LLM response was empty.")
        return content.strip()

    def _retry_after_seconds(self, exc):
        """Extract a bounded retry-after hint from a rate-limit error.

        Looks at the response header first, then the error message text for a
        "try again in Ns" hint. Returns a float in seconds, or None.
        """
        response = getattr(exc, "response", None)
        if response is not None and hasattr(response, "headers"):
            try:
                retry_after = float(response.headers.get("retry-after", 0))
                if retry_after > 0:
                    return retry_after
            except Exception:
                pass
        message = str(exc)
        match = _RETRY_AFTER_RE.search(message)
        if match:
            try:
                return float(match.group(1))
            except Exception:
                pass
        return None

    def _cloud_with_retry(self, fn, attempts=3):
        """Call `fn` (a hosted API request) with a bounded retry for rate limits.

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
                retry_after = self._retry_after_seconds(exc)
                if retry_after is not None:
                    wait = min(retry_after + 0.5, 30.0)
                logging.warning("Rate limit (429); retrying in %.1fs (attempt %d/%d)",
                                wait, attempt + 1, attempts)
                time.sleep(wait)
        raise last_exc  # pragma: no cover

    def vision(self, prompt, images, temperature=0.1, num_predict=1500, timeout=60):
        """Send rendered page images (base64 PNG strings) plus a text prompt to a
        vision model. Available on a hosted backend with a vision model.

        Used to transcribe scanned/handwritten PDFs into structured records.
        """
        model = self.models.get("vision")
        if not model:
            raise RuntimeError(f"No vision model configured for provider '{self.provider}'.")
        if self.provider == "local":
            raise RuntimeError(
                "Handwritten/scanned PDF extraction requires a hosted provider "
                "with a vision model. Switch backend and retry."
            )
        content = [{"type": "text", "text": prompt}]
        for b64 in images:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        try:
            return self._vision_once(prompt, content, model, temperature, num_predict, timeout)
        except TimeoutError:
            raise

    def _vision_once(self, prompt, content, model, temperature, num_predict, timeout):
        kwargs = {}
        if "json" in (prompt or "").lower() or model.startswith("qwen/"):
            kwargs["response_format"] = {"type": "json_object"}
        extra_body = self._thinking_body("vision")
        def _request():
            call_kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
                "max_tokens": num_predict,
                "timeout": timeout,
            }
            if extra_body:
                call_kwargs["extra_body"] = extra_body
            call_kwargs.update(kwargs)
            return self._cloud_client.chat.completions.create(**call_kwargs)

        completion = self._cloud_with_retry(_request)
        result = completion.choices[0].message.content
        if not result:
            raise RuntimeError("Vision response was empty.")
        return result.strip()

    def __repr__(self):
        return f"LLMProvider(provider={self.provider}, models={self.models})"


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def create_provider(provider="local", api_key=None, models=None, base_url=None):
    """Build an LLMProvider.

    Policy: never silently switch backend. If a hosted provider ('cloud' or
    'deepseek') is requested but its dependencies/key are missing, raise so the
    caller/user decides (no silent downgrade to local). Switching provider
    mid-session only happens through an explicit user action (see
    /api/provider/switch) — never automatically.
    """
    if provider == "cloud":
        if not GROQ_AVAILABLE:
            raise RuntimeError(
                "The Cloud provider is unavailable because the 'groq' package is not "
                "installed (pip install groq). Stay on Local or fix this first."
            )
        llm = LLMProvider("cloud", api_key=api_key or os.getenv("GROQ_API_KEY"), models=models, base_url=base_url)
        if not llm._cloud_client.api_key:
            raise RuntimeError("Missing GROQ_API_KEY. Set it in .env or pass api_key.")
        return llm
    if provider == "deepseek":
        try:
            from openai import OpenAI  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "The DeepSeek provider is unavailable because the 'openai' package is not "
                "installed (pip install openai). Choose another provider."
            )
        llm = LLMProvider("deepseek", api_key=api_key or os.getenv("DEEPSEEK_API_KEY"), models=models, base_url=base_url)
        if not llm._cloud_client.api_key:
            raise RuntimeError("Missing DEEPSEEK_API_KEY. Set it in .env or pass api_key.")
        return llm
    return LLMProvider("local", models=models)
