"""A scripted stand-in for a chat model: returns (or raises) prepared outputs in order."""

from typing import Any

import groq
import httpx
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.tool import tool_call
from langchain_core.runnables import RunnableLambda


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class Scripted:
    def __init__(self, *outputs: AIMessage | BaseException) -> None:
        self.outputs = list(outputs)
        self.seen: list[list[BaseMessage]] = []  # the messages each call received

    def _call(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    @property
    def model(self) -> RunnableLambda[Any, Any]:
        return RunnableLambda(self._call)


def ai(
    *calls: tuple[str, dict[str, Any]],
    text: Any = "",
    usage: tuple[int, int] | None = (10, 2),
) -> AIMessage:
    return AIMessage(
        content=text,
        tool_calls=[tool_call(name=n, args=a, id=f"c-{i}") for i, (n, a) in enumerate(calls)],
        usage_metadata=(
            None
            if usage is None
            else {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)}
        ),
    )


def groq_tool_use_failed(failed_generation: str) -> groq.BadRequestError:
    """Groq's 400 when the model's output isn't a valid (or required) tool call."""
    error = {"message": "x", "code": "tool_use_failed", "failed_generation": failed_generation}
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.example.test"))
    return groq.BadRequestError("Error code: 400", response=response, body={"error": error})
