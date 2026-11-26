"""Manual one-message live check (M1 Task 4). Not run in CI: it calls the provider.

    uv run python -m support.llm.ping gemini|groq

Sends one fixed message with no tools and prints the pinned settings, the reply and
the CallRecord. It never prints a key: the key is only checked for presence.
"""

import sys
from typing import get_args

from langchain_core.messages import BaseMessage, HumanMessage

from support.llm.config import ConfigError, Provider, load_check_config
from support.llm.wrapper import get_chat_model, invoke_with_record

PING_MESSAGE = "Reply with the single word: pong"


def main(argv: list[str]) -> int:
    providers: tuple[Provider, ...] = get_args(Provider)
    if len(argv) != 1 or argv[0] not in providers:
        print(f"usage: python -m support.llm.ping {'|'.join(providers)}", file=sys.stderr)
        return 2
    provider: Provider = argv[0]  # type: ignore[assignment]  # checked against Provider above
    try:
        cfg = load_check_config(provider)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    print(f"settings: {cfg}")
    messages: list[BaseMessage] = [HumanMessage(PING_MESSAGE)]
    reply, record = invoke_with_record(get_chat_model(cfg), messages, cfg)
    print(f"reply: {reply.content if reply is not None else None!r}")
    print(f"record: {record}")
    return 0 if reply is not None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
