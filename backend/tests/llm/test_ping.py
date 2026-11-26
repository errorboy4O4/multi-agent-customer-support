import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from support.llm import ping
from support.llm.config import ConfigError, LLMConfig

CFG = LLMConfig(provider="groq", model="groq-test-model", temperature=0.6, effort="medium")


def test_bad_usage_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert ping.main([]) == 2
    assert ping.main(["openai"]) == 2
    assert "gemini|groq" in capsys.readouterr().err


def test_config_error_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_provider: str) -> LLMConfig:
        raise ConfigError("Missing or empty in the environment / .env: GROQ_API_KEY")

    monkeypatch.setattr(ping, "load_check_config", fail)
    assert ping.main(["groq"]) == 1
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_prints_settings_reply_and_record_but_never_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-SECRET-value-123")
    monkeypatch.setattr(ping, "load_check_config", lambda _provider: CFG)
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="pong")]))
    monkeypatch.setattr(ping, "get_chat_model", lambda _cfg: fake)
    assert ping.main(["groq"]) == 0
    out = capsys.readouterr().out
    assert "groq-test-model" in out and "'pong'" in out and "latency_ms" in out
    assert "SECRET" not in out
