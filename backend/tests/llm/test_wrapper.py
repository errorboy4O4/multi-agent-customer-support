from types import SimpleNamespace
from typing import Any

import groq
import httpx
import pytest
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import GoogleRateLimitError
from langchain_groq import ChatGroq

from support.llm.config import ConfigError, LLMConfig
from support.llm.wrapper import classify_error, get_chat_model, invoke_with_record

GEMINI = LLMConfig(provider="gemini", model="gemini-test-model", temperature=None)
MESSAGES: list[BaseMessage] = [HumanMessage("Where is my order?")]
REQUEST = httpx.Request("POST", "https://api.example.test/v1/chat")


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def raising(exc: BaseException) -> RunnableLambda[Any, Any]:
    def _raise(_: Any) -> Any:
        raise exc

    return RunnableLambda(_raise)


def wrapped(outer: BaseException, cause: BaseException) -> BaseException:
    """Return `outer` raised `from cause`, the way the provider wrappers re-raise."""
    try:
        raise outer from cause
    except BaseException as e:
        return e


# --- classify_error -------------------------------------------------------------


def test_classify_error() -> None:
    assert classify_error(StatusError(429)) == "rate_limit"
    assert classify_error(StatusError(503)) == "server"
    assert classify_error(TimeoutError()) == "timeout"
    assert classify_error(ValueError()) is None


def test_classify_error_reads_code_and_response() -> None:
    with_code = Exception("x")
    with_code.code = 429  # type: ignore[attr-defined]
    assert classify_error(with_code) == "rate_limit"
    with_response = Exception("x")
    with_response.response = SimpleNamespace(status_code=500)  # type: ignore[attr-defined]
    assert classify_error(with_response) == "server"


def test_client_errors_are_not_retryable() -> None:
    # 400/401/404 mean our request is wrong; rerunning would hide a bug.
    for status in (400, 401, 403, 404):
        assert classify_error(StatusError(status)) is None


def test_classify_real_groq_errors() -> None:
    rate = groq.RateLimitError(
        "rate limited", response=httpx.Response(429, request=REQUEST), body=None
    )
    assert classify_error(rate) == "rate_limit"
    assert classify_error(groq.APITimeoutError(request=REQUEST)) == "timeout"


def test_classify_real_gemini_rate_limit() -> None:
    # langchain-google-genai re-raises a 429 as GoogleRateLimitError(msg): no status
    # attribute of its own, but it subclasses LangChain's ModelRateLimitError.
    assert classify_error(GoogleRateLimitError("Error calling model")) == "rate_limit"


def test_classify_langchain_model_errors() -> None:
    assert classify_error(ModelRateLimitError("x")) == "rate_limit"
    assert classify_error(ModelAPIError("x")) == "server"


def test_classify_follows_the_cause_chain() -> None:
    assert classify_error(wrapped(RuntimeError("outer"), StatusError(503))) == "server"
    assert classify_error(wrapped(RuntimeError("outer"), httpx.ReadTimeout("slow"))) == "timeout"


def test_classify_survives_a_cyclic_chain() -> None:
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    assert classify_error(a) is None


# --- invoke_with_record ---------------------------------------------------------


def test_record_reads_usage_metadata() -> None:
    reply = AIMessage(
        content="ok", usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}
    )
    message, record = invoke_with_record(
        GenericFakeChatModel(messages=iter([reply])), MESSAGES, GEMINI
    )
    assert message is not None and message.content == "ok"
    assert (record.provider, record.model) == ("gemini", "gemini-test-model")
    assert (record.input_tokens, record.output_tokens) == (12, 3)
    assert record.latency_ms >= 0
    assert record.error_class is None


def test_record_without_usage_is_none() -> None:
    model = GenericFakeChatModel(messages=iter([AIMessage(content="ok")]))
    _, record = invoke_with_record(model, MESSAGES, GEMINI)
    assert record.input_tokens is None
    assert record.output_tokens is None


def test_provider_error_returns_none_message() -> None:
    message, record = invoke_with_record(raising(StatusError(429)), MESSAGES, GEMINI)
    assert message is None
    assert record.error_class == "rate_limit"
    assert record.input_tokens is None
    assert record.latency_ms >= 0


def test_unclassified_error_propagates() -> None:
    with pytest.raises(ValueError):
        invoke_with_record(raising(ValueError("bug")), MESSAGES, GEMINI)


# --- get_chat_model (offline: builds the client, makes no request) ----------------


def test_gemini_model_has_retries_off_and_provider_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    model = get_chat_model(GEMINI)
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-test-model"
    assert model.max_retries == 1  # one attempt: this SDK reads 0 as "use the default"
    assert model.temperature is None  # provider default, not LangChain's 0.7


def test_groq_model_has_retries_off_and_pinned_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    model = get_chat_model(LLMConfig(provider="groq", model="groq-test-model", temperature=1.0))
    assert isinstance(model, ChatGroq)
    assert model.model_name == "groq-test-model"
    assert model.max_retries == 0
    assert model.temperature == 1.0


def test_groq_without_pinned_temperature_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # ChatGroq cannot omit temperature; silently using LangChain's 0.7 would break D3.
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    with pytest.raises(ConfigError, match="temperature"):
        get_chat_model(LLMConfig(provider="groq", model="groq-test-model", temperature=None))
