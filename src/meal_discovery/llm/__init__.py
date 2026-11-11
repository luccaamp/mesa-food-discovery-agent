"""LLM port and adapters: Gemini, Groq, local llama.cpp (Qwen) and OpenAI."""

from .registry import FallbackChatModel, build, describe, from_environment
from .types import ChatModel, ChatResult, Message, ProviderUnavailable, ToolCall, ToolSpec

__all__ = ["ChatModel", "ChatResult", "FallbackChatModel", "Message", "ProviderUnavailable",
           "ToolCall", "ToolSpec", "build", "describe", "from_environment"]
