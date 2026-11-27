"""The one place that builds provider clients, plus a per-call record (D8).

Library-level retries are off (decided 26 Nov 2026, Task 3): every HTTP request is one
CallRecord, and the caller (the M1 runner) owns reruns. Otherwise a single record could
hide several requests against the free-tier quota and distort D9's request counts.
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

import groq
import httpx
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from support.llm.config import ConfigError, LLMConfig

ErrorClass = Literal["rate_limit", "server", "timeout", "tool_use_failed"]
# tool_use_failed is the model's failure, not the provider's (decided 26 Nov 2026, Task 8):
# never rerun, and scored like a malformed tool call (D3).
RETRYABLE: frozenset[ErrorClass] = frozenset({"rate_limit", "server", "timeout"})

# google-genai can run on httpx2, a fork whose classes are not httpx subclasses.
_TIMEOUT_TYPES: tuple[type[BaseException], ...] = (
    TimeoutError,
    httpx.TimeoutException,
    groq.APITimeoutError,
)
try:
    import httpx2

    _TIMEOUT_TYPES += (httpx2.TimeoutException,)
except ImportError:  # pragma: no cover - depends on google-genai's own dependencies
    pass


@dataclass(frozen=True)
class CallRecord:
    provider: str
    model: str
    input_tokens: int | None  # None = the provider sent no usage data (never guessed as 0)
    output_tokens: int | None
    latency_ms: float
    error_class: ErrorClass | None
    # tool_use_failed only: what the model produced, as the provider reported it
    failed_generation: str | None = None


def get_chat_model(cfg: LLMConfig) -> BaseChatModel:
    """Temperature and effort are always passed, so LangChain's own defaults (0.7) never
    apply. None sends no value for that setting (D3: pinned where the provider allows)."""
    if cfg.provider == "gemini":
        # max_retries=1 is a single attempt: this SDK treats 0 as "use its default (6)".
        # temperature=None is passed explicitly, so the request leaves it out.
        return ChatGoogleGenerativeAI(
            model=cfg.model,
            temperature=cfg.temperature,
            reasoning_effort=cfg.effort,
            max_retries=1,
        )
    if cfg.temperature is None:
        # ChatGroq cannot leave temperature out; its fallback is LangChain's 0.7, not Groq's.
        raise ConfigError("Groq needs a pinned temperature number in models.yaml, not null")
    return ChatGroq(
        model=cfg.model,
        temperature=cfg.temperature,
        reasoning_effort=cfg.effort,
        max_retries=0,
    )


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """The exception, then whatever it was raised from, guarding against cycles."""
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        seen.add(id(link))
        yield link
        link = link.__cause__ or (None if link.__suppress_context__ else link.__context__)


def _status(link: BaseException) -> int | None:
    candidates: list[Any] = [
        getattr(link, "status_code", None),
        getattr(link, "code", None),
        getattr(getattr(link, "response", None), "status_code", None),
    ]
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def groq_failed_generation(exc: BaseException) -> str | None:
    """The model output behind Groq's 400 `tool_use_failed`, or None for any other error.

    Groq returns this when the model's output isn't a valid tool call, or isn't a tool
    call at all under a forced tool choice. It's the model failing, so the record keeps
    what it produced ("" if Groq sent nothing) instead of the run crashing on it.
    """
    for link in _chain(exc):
        if not isinstance(link, groq.BadRequestError):
            continue
        body = link.body
        error = body.get("error", body) if isinstance(body, dict) else None
        if isinstance(error, dict) and error.get("code") == "tool_use_failed":
            text = error.get("failed_generation")
            return text if isinstance(text, str) else ""
    return None


def classify_error(exc: BaseException) -> ErrorClass | None:
    """Sort a provider failure into a retryable class, or None (not ours to retry)."""
    for link in _chain(exc):
        if isinstance(link, ModelRateLimitError):
            return "rate_limit"
        if isinstance(link, ModelAPIError):
            return "server"
        if isinstance(link, _TIMEOUT_TYPES):
            return "timeout"
        status = _status(link)
        if status == 429:
            return "rate_limit"
        if status is not None and 500 <= status < 600:
            return "server"
    return None


def invoke_with_record(
    model: Runnable[Any, Any], messages: list[BaseMessage], cfg: LLMConfig
) -> tuple[AIMessage | None, CallRecord]:
    """One model call. A retryable provider error or Groq's tool_use_failed returns
    (None, record); any other error raises."""
    start = time.perf_counter()
    try:
        result = model.invoke(messages)
    except Exception as exc:
        failed = groq_failed_generation(exc)
        error_class: ErrorClass | None = "tool_use_failed" if failed is not None else None
        error_class = error_class or classify_error(exc)
        if error_class is None:
            raise
        latency_ms = (time.perf_counter() - start) * 1000
        return None, CallRecord(
            cfg.provider, cfg.model, None, None, latency_ms, error_class, failed
        )
    latency_ms = (time.perf_counter() - start) * 1000
    if not isinstance(result, AIMessage):
        raise TypeError(f"Expected an AIMessage from the model, got {type(result).__name__}")
    usage = result.usage_metadata
    return result, CallRecord(
        provider=cfg.provider,
        model=cfg.model,
        input_tokens=usage["input_tokens"] if usage else None,
        output_tokens=usage["output_tokens"] if usage else None,
        latency_ms=latency_ms,
        error_class=None,
    )
