"""Claude access (Anthropic Python SDK) for extraction and answers.

Every request goes to the beta Messages endpoint with server-side refusal fallback
(`fallbacks="default"`): when a safety classifier declines a request, the API re-runs it on the
recommended fallback model inside the same call. The system prompt is sent as a cached block, so
repeated calls with the same instructions (e.g. one extraction per document) reuse the prompt cache.
Thinking is always on for claude-opus-5-5; `effort` is the only depth control.

Errors are mapped to three types so callers can fall back to the offline engines:
  LLMUnavailable  no credentials, LLM use disabled, or credentials rejected (401/403)
  LLMRefusal      the request was declined (stop_reason "refusal", after any fallback)
  LLMError        everything else: rate limits, API or network errors, truncated or unparseable output
"""
from __future__ import annotations

import json
import os

import anthropic

from . import config

FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MAX_TOKENS = 16000
_TRUNCATED = {"max_tokens", "model_context_window_exceeded"}


class LLMError(Exception):
    """Claude could not produce a usable result."""


class LLMUnavailable(LLMError):
    """Claude is not configured or disabled, or it rejected the credentials."""


class LLMRefusal(LLMError):
    """Claude declined the request (stop_reason == "refusal")."""


def get_client() -> anthropic.Anthropic:
    """A client using the configured credentials (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN)."""
    if not config.llm_available():
        raise LLMUnavailable("Claude is not configured (set ANTHROPIC_API_KEY in .env) or KG_LLM_DISABLED is set")
    workspace = os.getenv("ANTHROPIC_WORKSPACE_ID")      # needed for keys not scoped to a workspace
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)


def structured_call(system: str, user: str, schema: dict, *, effort: str, max_tokens: int = DEFAULT_MAX_TOKENS,
                    client=None, model: str | None = None) -> dict:
    """One request constrained to `schema` (structured outputs); returns the parsed JSON object."""
    output_config = {"effort": effort, "format": {"type": "json_schema", "schema": schema}}
    text = _response_text(_create(client, system, user, output_config, max_tokens, model))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Claude returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"Claude returned a JSON {type(data).__name__}, expected an object")
    return data


def text_call(system: str, user: str, *, effort: str, max_tokens: int = DEFAULT_MAX_TOKENS, client=None,
              model: str | None = None) -> str:
    """One free-text request; returns the answer text."""
    return _response_text(_create(client, system, user, {"effort": effort}, max_tokens, model)).strip()


def _create(client, system: str, user: str, output_config: dict, max_tokens: int, model: str | None):
    client = client if client is not None else get_client()
    try:
        return client.beta.messages.create(
            model=model or config.LLM_MODEL,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config=output_config,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise LLMUnavailable(f"Claude rejected the credentials (HTTP {exc.status_code}): {exc.message}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"Claude rate limit reached (HTTP 429): {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Claude API error (HTTP {exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"cannot reach the Claude API: {exc.message}") from exc
    except anthropic.APIError as exc:
        raise LLMError(f"unexpected Claude API response: {exc.message}") from exc


def _response_text(response) -> str:
    """The text blocks of a response, after checking why generation stopped.

    Thinking blocks (empty under the default display) and fallback switch-point markers are
    skipped; a non-streaming response never contains a declined model's partial output.
    """
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        raise LLMRefusal(_refusal_message(response))
    if stop in _TRUNCATED:
        raise LLMError(f"Claude's output was cut off (stop_reason={stop}); raise max_tokens")
    text = "".join(block.text for block in (getattr(response, "content", None) or [])
                   if getattr(block, "type", None) == "text")
    if not text.strip():
        raise LLMError(f"Claude returned no text (stop_reason={stop})")
    return text


def _refusal_message(response) -> str:
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    explanation = getattr(details, "explanation", None)
    message = "Claude declined the request" + (f" (category: {category})" if category else "")
    return f"{message}: {explanation}" if explanation else message
