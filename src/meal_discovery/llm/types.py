"""Provider-neutral chat contract: the port every LLM adapter implements."""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderUnavailable(Exception):
    """A provider could not produce a valid answer.

    `reason` is a short sanitized code (never a provider body, URL or key) and
    `attempts` counts requests actually sent, each charged to the local quota.
    """

    def __init__(self, reason="unavailable", *, attempts=0, provider=None):
        self.reason = reason
        self.attempts = attempts
        self.provider = provider
        super().__init__("Provider unavailable: " + reason)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict
    # Provider-specific opaque data that must be echoed back on the next turn
    # (for example Gemini thought signatures). Never shown to users.
    extra: dict = field(default_factory=dict)


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall]
    usage: dict
    provider: str
    model: str


# Messages use a small neutral shape that adapters translate:
#   {"role": "system" | "user", "content": str}
#   {"role": "assistant", "content": str | None, "tool_calls": [ToolCall, ...]}
#   {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Message = dict[str, Any]


@runtime_checkable
class ChatModel(Protocol):
    provider: str
    model: str

    @property
    def configured(self) -> bool: ...

    def chat(self, messages: list[Message], *, tools: list[ToolSpec] | None = None,
             json_schema: dict | None = None, max_tokens: int = 256,
             temperature: float = 0.0) -> ChatResult: ...
