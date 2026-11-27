from typing import Any

from evals.model_check.summarize import summarize


def run_file(
    index: int,
    score: float | None,
    *,
    valid: bool = True,
    wrong_refunds: int = 0,
    errors: int = 0,
    convos: list[dict[str, Any]] | None = None,
    missing_usage: int = 0,
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": f"gemini-{index}",
        "run_index": index,
        "settings": {
            "provider": "gemini",
            "model": "m",
            "temperature": None,
            "effort": "medium",
            "prompt_version": "1",
        },
        "score": score,
        "valid": valid,
        "errors": errors,
        "wrong_refunds": wrong_refunds,
        "missing_usage": missing_usage,
        "cases": cases or [],
        "conversations": convos or [],
    }


def convo(requests: int, inp: int, out: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": "cv",
        "requests": requests,
        "error_calls": 0,
        "input_tokens": inp,
        "output_tokens": out,
        "missing_usage": 0,
        "unmatched_calls": 0,
        "invalid_calls": 0,
        "hit_cap": False,
        "error": False,
        **extra,
    }


def test_t1_pass_with_three_valid_runs() -> None:
    text = summarize([run_file(i, s) for i, s in [(1, 0.95), (2, 0.95), (3, 0.85)]])
    assert "Early estimates: draft prompt, canned tool results" in text
    assert "T1: **PASS**" in text
    assert "0.917" in text  # the mean, never the best run


def test_t1_fail_on_one_wrong_refund() -> None:
    files = [run_file(1, 1.0, wrong_refunds=1), run_file(2, 1.0), run_file(3, 1.0)]
    assert "T1: **FAIL**" in summarize(files)


def test_t1_not_computable_without_exactly_three_valid_runs() -> None:
    files = [run_file(1, 1.0), run_file(2, 1.0), run_file(3, None, valid=False, errors=3)]
    text = summarize(files)
    assert "T1: not computable" in text
    assert "invalid runs: 1" in text


def test_conversation_means_and_counts_are_shown() -> None:
    convos = [convo(4, 1000, 100), convo(2, 600, 40, unmatched_calls=1)]
    files = [run_file(i, 1.0, convos=convos, missing_usage=1) for i in (1, 2, 3)]
    text = summarize(files)
    assert "mean requests per conversation: 3.0" in text
    assert "mean input tokens per conversation: 800" in text
    assert "mean output tokens per conversation (including thinking): 70" in text
    assert "unmatched calls: 3" in text
    assert "calls with no usage data: 3" in text


def test_errored_conversations_left_out_of_means() -> None:
    convos = [convo(4, 1000, 100), convo(1, 50, 5, error=True)]
    files = [run_file(i, 1.0, convos=convos) for i in (1, 2, 3)]
    text = summarize(files)
    assert "mean requests per conversation: 4.0" in text
    assert "conversations with a provider error (left out of means): 3" in text


def test_failed_attempts_are_shown_next_to_requests() -> None:
    # D9 judges quota from every request sent, failed attempts included.
    rerun_case = {"records": [{"error_class": "rate_limit"}, {"error_class": None}]}
    convos = [convo(4, 1000, 100, error_calls=2)]
    files = [run_file(i, 1.0, convos=convos, cases=[rerun_case]) for i in (1, 2, 3)]
    text = summarize(files)
    assert (
        "mean requests per conversation: 4.0; failed attempts (they count against the quota): "
        "6 in conversations, 3 in cases"
    ) in text


def test_summary_states_the_arguments_limitation() -> None:
    # Accepted for M1 on 27 Nov 2026: run files keep the called tool's name, not its args.
    text = summarize([run_file(i, 1.0) for i in (1, 2, 3)])
    assert "record the called tool's name, not its arguments" in text
    assert "M5" in text
