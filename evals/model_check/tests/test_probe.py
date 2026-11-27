from evals.model_check.probe_forced_tool import probe, probe_section
from evals.model_check.tests.fakes import Scripted, StatusError, ai, groq_tool_use_failed
from support.llm.config import LLMConfig

CFG = LLMConfig("gemini", "test-model", None, "medium")
HANDOFF = {"reason": "human_requested", "summary": "Has a question."}


def test_probe_records_each_attempt() -> None:
    fake = Scripted(ai(("create_handoff", HANDOFF)), ai(text="Hello!"), StatusError(429))
    results = probe(fake.model, CFG, times=3, sleep=lambda _s: None)
    assert [r.called_handoff for r in results] == [True, False, None]
    assert results[2].error_class == "rate_limit"
    assert fake.seen[0][-1].content  # a neutral customer message was sent


def test_probe_section_reports_yes_no_per_attempt() -> None:
    fake = Scripted(ai(("create_handoff", HANDOFF)), ai(("create_handoff", HANDOFF)), ai(text="Hi"))
    section = probe_section(
        CFG, probe(fake.model, CFG, times=3, sleep=lambda _s: None), "2026-11-26"
    )
    assert "gemini" in section and "test-model" in section and "2026-11-26" in section
    assert "2 of 3" in section


def test_probe_records_groq_tool_use_failed_as_no() -> None:
    fake = Scripted(groq_tool_use_failed("Sure thing! What's your order number?"))
    results = probe(fake.model, CFG, times=1, sleep=lambda _s: None)
    assert (results[0].called_handoff, results[0].error_class) == (False, "tool_use_failed")
    section = probe_section(CFG, results, "2026-11-27")
    assert "0 of 1" in section
    assert "no (rejected by provider: tool_use_failed)" in section
