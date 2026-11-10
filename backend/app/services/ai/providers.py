"""Provider-independent LLM access. Add a provider by implementing ``complete_json``."""

import json
import re
from typing import Protocol

import httpx

from app.config import Settings, get_settings


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete_json(self, system: str, user: str) -> dict: ...


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model response (tolerates code fences and preambles)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("model response contained no JSON object")
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("model response was not valid JSON") from exc
    if not isinstance(data, dict):
        raise LLMError("model response JSON was not an object")
    return data


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self._key = api_key
        self._timeout = timeout
        self._transport = transport

    async def complete_json(self, system: str, user: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
            try:
                resp = await http.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": self.model, "max_tokens": 2500, "temperature": 0.2, "system": system, "messages": [{"role": "user", "content": user}]},
                )
            except httpx.HTTPError as exc:
                raise LLMError(f"Anthropic request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise LLMError(f"Anthropic returned HTTP {resp.status_code}")
        blocks = resp.json().get("content") or []
        return extract_json("".join(b.get("text", "") for b in blocks if b.get("type") == "text"))


class OpenAICompatibleProvider:
    """Works with OpenAI and any OpenAI-compatible endpoint (OpenRouter, Ollama, vLLM, Azure gateways)."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def complete_json(self, system: str, user: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
            try:
                resp = await http.post(
                    f"{self._base}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={"model": self.model, "temperature": 0.2, "response_format": {"type": "json_object"},
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                )
            except httpx.HTTPError as exc:
                raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise LLMError(f"LLM endpoint returned HTTP {resp.status_code}")
        choices = resp.json().get("choices") or []
        if not choices:
            raise LLMError("LLM endpoint returned no choices")
        return extract_json(choices[0].get("message", {}).get("content") or "")


DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}


def get_provider(settings: Settings | None = None) -> LLMProvider | None:
    """Return the configured provider, or None when the deterministic rules engine should be used alone."""
    settings = settings or get_settings()
    if not settings.llm_configured:
        return None
    model = settings.llm_model or DEFAULT_MODELS[settings.llm_provider]
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key or "", model, settings.llm_timeout_seconds)
    return OpenAICompatibleProvider(settings.openai_api_key or "", model, settings.openai_base_url, settings.llm_timeout_seconds)
