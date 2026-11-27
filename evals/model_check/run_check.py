"""M1 model-check runner (D3, D8, D9): the 20 cases, then the 5 conversations, per run.

    uv run --project backend python evals/model_check/run_check.py --provider gemini --runs 3

Each run writes evals/results/m1-model-check/<run_id>.json with the full settings, every
CallRecord and the git commit. Provider errors (429, 5xx, timeout) are reruns, never
fails: at most 2 per case, then the case is an `error` and leaves N; a run with more than
2 errors is invalid (D3). There is no fallback to another provider inside a run.
"""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from pydantic import ValidationError

if __package__ in (None, ""):  # run as a script: put the repo root on the path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.model_check.check_files import (  # noqa: E402
    CannedResult,
    Conversation,
    load_cases,
    load_conversations,
    load_system_prompt,
)
from evals.model_check.scoring import CaseResult, CheckCase, case_messages, score_case  # noqa: E402
from support.llm.config import LLMConfig, Provider, load_check_config  # noqa: E402
from support.llm.wrapper import CallRecord, get_chat_model, invoke_with_record  # noqa: E402
from support.tools.schemas import TOOL_SPECS, as_langchain_tools  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "evals" / "results" / "m1-model-check"
MAX_ERRORS_FOR_VALID_RUN = 2  # D3: more than 2 errors after reruns = invalid run
DEFAULT_RERUN_WAIT_S = 20.0

Sleep = Callable[[float], None]


@dataclass
class CaseOutcome:
    result: CaseResult
    records: list[CallRecord]  # every request for this case, reruns included


@dataclass
class ConvoResult:
    id: str
    requests: int = 0  # model calls that returned a reply
    error_calls: int = 0  # requests that failed with a provider error
    input_tokens: int = 0  # summed over calls that had usage data
    output_tokens: int = 0  # includes thinking for both providers (models.md)
    missing_usage: int = 0
    unmatched_calls: int = 0
    invalid_calls: int = 0
    hit_cap: bool = False
    error: bool = False  # a provider error outlived its reruns; the conversation stopped
    records: list[CallRecord] = field(default_factory=list)


@dataclass
class RunResult:
    run_index: int
    cases: list[CaseOutcome]
    reruns: int
    errors: int
    wrong_refunds: int
    missing_usage: int
    score: float | None  # passed / (cases - errors); None if every case errored
    valid: bool
    conversations: list[ConvoResult] = field(default_factory=list)


class _Caller:
    """Sends requests with pacing and reruns. Library retries are off (Task 3), so every
    attempt here is exactly one request and one CallRecord."""

    def __init__(
        self,
        model: Runnable[Any, Any],
        cfg: LLMConfig,
        *,
        max_reruns: int,
        min_interval_s: float,
        rerun_wait_s: float,
        sleep: Sleep,
    ) -> None:
        self.model, self.cfg, self.max_reruns = model, cfg, max_reruns
        self.min_interval_s, self.rerun_wait_s, self.sleep = min_interval_s, rerun_wait_s, sleep
        self.sent = 0

    def call(self, messages: list[BaseMessage]) -> tuple[AIMessage | None, list[CallRecord]]:
        records: list[CallRecord] = []
        for attempt in range(self.max_reruns + 1):
            if attempt:
                self.sleep(self.rerun_wait_s)
            elif self.sent and self.min_interval_s > 0:
                self.sleep(self.min_interval_s)
            self.sent += 1
            reply, record = invoke_with_record(self.model, messages, self.cfg)
            records.append(record)
            if reply is not None:
                return reply, records
        return None, records


def run_cases(
    model: Runnable[Any, Any],
    cfg: LLMConfig,
    cases: Sequence[CheckCase],
    run_index: int,
    max_reruns: int = 2,
    *,
    system_prompt: str,
    min_interval_s: float = 0.0,
    rerun_wait_s: float = DEFAULT_RERUN_WAIT_S,
    sleep: Sleep = time.sleep,
    caller: _Caller | None = None,
) -> RunResult:
    caller = caller or _Caller(
        model,
        cfg,
        max_reruns=max_reruns,
        min_interval_s=min_interval_s,
        rerun_wait_s=rerun_wait_s,
        sleep=sleep,
    )
    outcomes: list[CaseOutcome] = []
    for case in cases:
        reply, records = caller.call([SystemMessage(system_prompt), *case_messages(case)])
        if reply is None:
            result = CaseResult(case.id, False, "error", None, False)
        else:
            result = score_case(case, reply)
        outcomes.append(CaseOutcome(result, records))
    errors = sum(o.result.reason == "error" for o in outcomes)
    scored = len(outcomes) - errors
    passed = sum(o.result.passed for o in outcomes)
    return RunResult(
        run_index=run_index,
        cases=outcomes,
        reruns=sum(len(o.records) - 1 for o in outcomes),
        errors=errors,
        wrong_refunds=sum(o.result.wrong_refund for o in outcomes),
        missing_usage=sum(
            r.error_class is None and r.input_tokens is None for o in outcomes for r in o.records
        ),
        score=passed / scored if scored else None,
        valid=errors <= MAX_ERRORS_FOR_VALID_RUN,
    )


def _canned_matches(canned: CannedResult, args: dict[str, Any]) -> bool:
    for key, expected in canned.args_match.items():
        actual = args.get(key)
        if key == "item_ids" and isinstance(actual, list) and isinstance(expected, list):
            if set(actual) != set(expected):
                return False
        elif actual != expected:
            return False
    return True


def _tool_result(convo: Conversation, name: str, args: Any, result: ConvoResult) -> dict[str, Any]:
    """The canned result, or a D14 error class (decided 26 Nov 2026, Task 7)."""
    spec = TOOL_SPECS.get(name)
    try:
        if spec is None or not isinstance(args, dict):
            raise ValueError
        spec.model_validate(args)
    except (ValueError, ValidationError):
        result.invalid_calls += 1
        return {"error": "invalid_argument"}
    for canned in convo.canned:
        if canned.tool == name and _canned_matches(canned, args):
            return canned.result
    result.unmatched_calls += 1
    return {"error": "not_found"}


def _add_usage(result: ConvoResult, records: list[CallRecord]) -> None:
    for r in records:
        result.records.append(r)
        if r.error_class is not None:
            result.error_calls += 1
            continue
        result.requests += 1
        if r.input_tokens is None or r.output_tokens is None:
            result.missing_usage += 1
        else:
            result.input_tokens += r.input_tokens
            result.output_tokens += r.output_tokens


def run_conversation(
    model: Runnable[Any, Any],
    cfg: LLMConfig,
    convo: Conversation,
    max_model_calls_per_turn: int = 6,
    *,
    system_prompt: str,
    max_reruns: int = 2,
    min_interval_s: float = 0.0,
    rerun_wait_s: float = DEFAULT_RERUN_WAIT_S,
    sleep: Sleep = time.sleep,
    caller: _Caller | None = None,
) -> ConvoResult:
    caller = caller or _Caller(
        model,
        cfg,
        max_reruns=max_reruns,
        min_interval_s=min_interval_s,
        rerun_wait_s=rerun_wait_s,
        sleep=sleep,
    )
    result = ConvoResult(convo.id)
    messages: list[BaseMessage] = [SystemMessage(system_prompt)]
    for turn in convo.turns:
        messages.append(HumanMessage(turn))
        for _ in range(max_model_calls_per_turn):
            reply, records = caller.call(messages)
            _add_usage(result, records)
            if reply is None:
                result.error = True
                return result
            messages.append(reply)  # unchanged: Gemini's thought signatures ride along
            calls = [(c["name"], c["args"], c["id"]) for c in reply.tool_calls]
            calls += [
                (c.get("name") or "", c.get("args"), c.get("id")) for c in reply.invalid_tool_calls
            ]
            if not calls:
                break
            for name, args, call_id in calls:
                if name not in TOOL_SPECS or not isinstance(args, dict):
                    result.invalid_calls += 1
                    content: dict[str, Any] = {"error": "invalid_argument"}
                else:
                    content = _tool_result(convo, name, args, result)
                messages.append(
                    ToolMessage(
                        json.dumps(content, ensure_ascii=False),
                        tool_call_id=call_id or "",
                        name=name,
                    )
                )
        else:
            result.hit_cap = True  # still calling tools after the cap: stop the conversation
            return result
    return result


def build_run_record(
    cfg: LLMConfig,
    run: RunResult,
    *,
    run_id: str,
    started_at: str,
    prompt_version: str,
    commit: str,
    dirty: bool,
) -> dict[str, Any]:
    record = asdict(run)
    return {
        "run_id": run_id,
        "started_at": started_at,
        "commit": commit,
        "dirty": dirty,  # True = uncommitted changes, so the commit alone doesn't prove the setup
        "settings": {
            "provider": cfg.provider,
            "model": cfg.model,
            "temperature": cfg.temperature,
            "effort": cfg.effort,
            "prompt_version": prompt_version,
        },
        **record,
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the M1 model check (D9).")
    parser.add_argument("--provider", choices=["gemini", "groq"], required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--first-run", type=int, default=1, help="index of the first run")
    parser.add_argument("--min-interval-s", type=float, default=0.0)
    parser.add_argument("--rerun-wait-s", type=float, default=DEFAULT_RERUN_WAIT_S)
    args = parser.parse_args(argv)
    provider: Provider = args.provider

    cfg = load_check_config(provider)
    cases, convos = load_cases(), load_conversations()
    prompt_version, prompt = load_system_prompt()
    model = get_chat_model(cfg).bind_tools(as_langchain_tools())
    commit, dirty = _git("rev-parse", "HEAD"), bool(_git("status", "--porcelain"))
    if dirty:
        print("warning: uncommitted changes; the result file records dirty=true")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    caller = _Caller(
        model,
        cfg,
        max_reruns=2,
        min_interval_s=args.min_interval_s,
        rerun_wait_s=args.rerun_wait_s,
        sleep=time.sleep,
    )
    for run_index in range(args.first_run, args.first_run + args.runs):
        started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        run = run_cases(model, cfg, cases, run_index, system_prompt=prompt, caller=caller)
        run.conversations = [
            run_conversation(model, cfg, c, system_prompt=prompt, caller=caller) for c in convos
        ]
        run_id = f"{provider}-{started.replace(':', '')}-r{run_index}"
        record = build_run_record(
            cfg,
            run,
            run_id=run_id,
            started_at=started,
            prompt_version=prompt_version,
            commit=commit,
            dirty=dirty,
        )
        path = RESULTS_DIR / f"{run_id}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"run {run_index}: score={run.score} errors={run.errors} valid={run.valid} "
            f"wrong_refunds={run.wrong_refunds} -> {path.relative_to(REPO_ROOT)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
