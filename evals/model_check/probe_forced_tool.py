"""Does forced tool choice work on each provider (D14)?

    uv run --project backend python evals/model_check/probe_forced_tool.py

Binds only create_handoff, forces that tool, and sends a neutral message 3 times per
provider. Prints each result and appends them to models.md. If forcing isn't supported,
the fallback path is decided in M4 as a recorded deviation, not here.
"""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable

if __package__ in (None, ""):  # run as a script: put the repo root on the path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.llm.config import LLMConfig, Provider, load_check_config  # noqa: E402
from support.llm.wrapper import ErrorClass, get_chat_model, invoke_with_record  # noqa: E402
from support.tools.schemas import as_langchain_tools  # noqa: E402

MODELS_MD = Path(__file__).resolve().parent / "models.md"
HANDOFF = "create_handoff"
NEUTRAL_MESSAGE = "Hello, I have a question about my order."
PROBE_INTERVAL_S = 5.0


@dataclass(frozen=True)
class ProbeResult:
    attempt: int
    called_handoff: bool | None  # None = provider error, no answer
    reason: str | None
    error_class: ErrorClass | None


def probe(
    model: Runnable[Any, Any],
    cfg: LLMConfig,
    times: int = 3,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for attempt in range(1, times + 1):
        if attempt > 1:
            sleep(PROBE_INTERVAL_S)
        reply, record = invoke_with_record(model, [HumanMessage(NEUTRAL_MESSAGE)], cfg)
        if reply is None:
            results.append(ProbeResult(attempt, None, None, record.error_class))
            continue
        handoffs = [c for c in reply.tool_calls if c["name"] == HANDOFF]
        reason = handoffs[0]["args"].get("reason") if handoffs else None
        results.append(ProbeResult(attempt, bool(handoffs), reason, None))
    return results


def probe_section(cfg: LLMConfig, results: list[ProbeResult], date: str) -> str:
    yes = sum(r.called_handoff is True for r in results)
    rows = "\n".join(
        f"| {r.attempt} | "
        + (
            "error: " + str(r.error_class)
            if r.called_handoff is None
            else "yes"
            if r.called_handoff
            else "no"
        )
        + f" | {r.reason or ''} |"
        for r in results
    )
    return (
        f"\n### Forced tool choice probe (D14): {cfg.provider} `{cfg.model}`, {date}\n\n"
        f"Only `{HANDOFF}` bound and forced; neutral message {NEUTRAL_MESSAGE!r}. "
        f"Result: {yes} of {len(results)} responses were a `{HANDOFF}` call.\n\n"
        "| Attempt | create_handoff call? | reason argument |\n|---|---|---|\n"
        f"{rows}\n"
    )


def main() -> int:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    handoff_tool = [t for t in as_langchain_tools() if t.name == HANDOFF]
    sections: list[str] = []
    provider: Provider
    for provider in get_args(Provider):
        cfg = load_check_config(provider)
        model = get_chat_model(cfg).bind_tools(handoff_tool, tool_choice=HANDOFF)
        results = probe(model, cfg)
        for r in results:
            print(f"{provider} attempt {r.attempt}: {r}")
        sections.append(probe_section(cfg, results, date))
    with MODELS_MD.open("a", encoding="utf-8") as f:
        f.write("".join(sections))
    print(f"appended {len(sections)} sections to {MODELS_MD.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
