"""AI provider layer. Each provider turns an AIRequest into an AIResponse.

- AnthropicProvider: official `anthropic` SDK, Messages API, structured outputs via
  output_config.format (JSON schema), optional server-side refusal fallback.
- OpenAIProvider: official `openai` SDK (Chat Completions with json_schema response format);
  also used for OpenAI-compatible endpoints via base_url.
- FakeProvider: no network call; deterministic rule-based answers (tests, demo, offline use).

Model names come from the ai_models table, never from code.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AIImage:
    data: bytes
    media_type: str = "image/jpeg"
    label: str | None = None


@dataclass
class AIRequest:
    function: str
    system: str
    text: str
    images: list[AIImage] = field(default_factory=list)
    schema: dict[str, Any] | None = None
    max_tokens: int = 8000
    effort: str | None = None
    context: dict[str, Any] = field(default_factory=dict)  # structured context for the fake provider


@dataclass
class AIResponse:
    text: str
    data: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str | None = None
    duration_ms: int = 0
    refused: bool = False


@dataclass
class ChatTurn:
    """Result of one tool-using chat step."""

    text: str
    tool_calls: list[dict[str, Any]]  # {id, name, input}
    raw_content: Any
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class Provider(Protocol):
    def complete(
        self, model_name: str, request: AIRequest, api_key: str | None, options: dict[str, Any]
    ) -> AIResponse: ...

    def chat(
        self,
        model_name: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        api_key: str | None,
        options: dict[str, Any],
    ) -> ChatTurn: ...


class ProviderError(Exception):
    """Transient or configuration error of a provider (eligible for the fallback model)."""


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start > 0:
        text = text[start:]
    return json.loads(text)


# ---------------------------------------------------------------------------------- Anthropic


class AnthropicProvider:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url

    def _client(self, api_key: str | None):
        import anthropic

        if not api_key:
            raise ProviderError("no API key configured for Anthropic")
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 2, "timeout": 300.0}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return anthropic.Anthropic(**kwargs)

    def complete(
        self, model_name: str, request: AIRequest, api_key: str | None, options: dict[str, Any]
    ) -> AIResponse:
        import anthropic

        client = self._client(api_key)
        content: list[dict[str, Any]] = []
        for img in request.images:
            if img.label:
                content.append({"type": "text", "text": img.label})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": base64.standard_b64encode(img.data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": request.text})
        params: dict[str, Any] = {
            "model": model_name,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": content}],
        }
        output_config: dict[str, Any] = {}
        if request.schema:
            output_config["format"] = {"type": "json_schema", "schema": request.schema}
        if request.effort:
            output_config["effort"] = request.effort
        if output_config:
            params["output_config"] = output_config
        started = time.monotonic()
        try:
            if options.get("fallbacks"):
                # server-side refusal fallback: the API re-runs a declined request on a suitable model
                response = client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
                )
            else:
                response = client.messages.create(**params)
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise ProviderError(str(exc)) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError("authentication failed") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"{exc.status_code}: {exc.message}") from exc
        duration = int((time.monotonic() - started) * 1000)
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        refused = response.stop_reason == "refusal"
        data = None
        if request.schema and text and not refused:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
        return AIResponse(
            text=text,
            data=data,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason,
            duration_ms=duration,
            refused=refused,
        )

    def chat(self, model_name, system, messages, tools, api_key, options) -> ChatTurn:
        import anthropic

        client = self._client(api_key)
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=options.get("max_tokens", 8000),
                # the long system prompt (app guide, settings) is the same in every round: cache it
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=[{**t, "strict": True} for t in tools],
                output_config={"effort": options.get("effort", "medium")},
            )
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise ProviderError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"{exc.status_code}: {exc.message}") from exc
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            {"id": b.id, "name": b.name, "input": b.input} for b in response.content if b.type == "tool_use"
        ]
        return ChatTurn(
            text=text,
            tool_calls=calls,
            raw_content=[b.model_dump(exclude_none=True) for b in response.content],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
        )


# ---------------------------------------------------------------------------------- OpenAI


class OpenAIProvider:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url

    def _client(self, api_key: str | None):
        import openai

        if not api_key:
            raise ProviderError("no API key configured for OpenAI")
        return openai.OpenAI(api_key=api_key, base_url=self.base_url or None, max_retries=2, timeout=300.0)

    def complete(
        self, model_name: str, request: AIRequest, api_key: str | None, options: dict[str, Any]
    ) -> AIResponse:
        import openai

        client = self._client(api_key)
        content: list[dict[str, Any]] = []
        for img in request.images:
            if img.label:
                content.append({"type": "text", "text": img.label})
            b64 = base64.standard_b64encode(img.data).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{img.media_type};base64,{b64}"}})
        content.append({"type": "text", "text": request.text})
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": content}],
            "max_completion_tokens": request.max_tokens,
        }
        if request.schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.function, "schema": request.schema, "strict": False},
            }
        started = time.monotonic()
        try:
            response = client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as exc:
            raise ProviderError(str(exc)) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"{exc.status_code}: {exc.message}") from exc
        text = response.choices[0].message.content or ""
        data = None
        if request.schema and text:
            try:
                data = _extract_json(text)
            except (json.JSONDecodeError, ValueError):
                data = None
        usage = response.usage
        return AIResponse(
            text=text,
            data=data,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model,
            stop_reason=response.choices[0].finish_reason,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def chat(self, model_name, system, messages, tools, api_key, options) -> ChatTurn:
        raise ProviderError("tool chat is implemented for Anthropic and the fake provider")


# ---------------------------------------------------------------------------------- registry


def get_provider(kind: str, base_url: str | None = None) -> Provider:
    if kind == "anthropic":
        return AnthropicProvider(base_url)
    if kind in ("openai", "openai_compatible"):
        return OpenAIProvider(base_url)
    if kind == "fake":
        from app.ai.fake import FakeProvider

        return FakeProvider()
    raise ProviderError(f"unknown provider kind {kind!r}")
