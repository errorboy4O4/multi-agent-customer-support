from evals.model_check.probe_forced_tool import probe, probe_section
from evals.model_check.tests.fakes import Scripted, StatusError, ai
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
