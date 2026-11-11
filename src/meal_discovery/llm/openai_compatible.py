"""Chat Completions adapter for OpenAI-compatible providers.

One implementation serves Groq (free tier, open models), a local llama.cpp
server running Qwen, and OpenAI itself. Only the base URL, key, model naming
and a few provider options differ.
"""

import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import Request

from . import resilience
from .types import ChatResult, ProviderUnavailable, ToolCall

MODEL_PATTERN = re.compile(r"[A-Za-z0-9._/:-]{1,100}")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "model_env": "GROQ_MODEL", "default_model": "openai/gpt-oss-120b"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "model_env": "OPENAI_MODEL", "default_model": ""},
    "local": {"base_url": None, "key_env": None, "model_env": "LOCAL_LLM_MODEL", "default_model": "meal-local"},
}


class OpenAICompatibleChatModel:
    def __init__(self, provider, model=None, key=None, base_url=None):
        if provider not in PROVIDERS:
            raise ValueError("Unknown OpenAI-compatible provider")
        spec = PROVIDERS[provider]
        self.provider = provider
        self.model = model or os.environ.get(spec["model_env"]) or spec["default_model"]
        self.key = key if key is not None else (os.environ.get(spec["key_env"], "") if spec["key_env"] else "")
        if provider == "local":
            base_url = base_url or os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8081")
            base_url = base_url.rstrip("/") + "/v1"
        self.base_url = (base_url or spec["base_url"]).rstrip("/")

    @property
    def configured(self):
        if self.provider == "local":
            return bool(self.model)
        return bool(self.key and self.model)

    @property
    def endpoint(self):
        """Server root, used by the local health check."""
        return self.base_url.removesuffix("/v1")

    def chat(self, messages, *, tools=None, json_schema=None, max_tokens=256, temperature=0.0):
        if not self.configured:
            raise ProviderUnavailable("not_configured", provider=self.provider)
        if not MODEL_PATTERN.fullmatch(self.model):
            raise ProviderUnavailable("invalid_model_configuration", provider=self.provider)
        if self.provider == "local":
            parsed = urlsplit(self.base_url)
            if parsed.scheme != "http" or parsed.hostname not in LOOPBACK:
                raise ProviderUnavailable("local_endpoint_must_be_loopback", provider=self.provider)
            policy = resilience.RetryPolicy(max_attempts=1, attempt_timeout=30, total_timeout=30)
        else:
            policy = resilience.budget_policy(self.provider)
        payload = {"model": self.model, "messages": [_message(message) for message in messages],
                   "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        if self.provider == "local":
            payload["seed"] = 42
        if self.provider == "groq" and self.model.startswith("openai/gpt-oss"):
            # Short classification and tool selection: keep hidden reasoning small.
            payload["reasoning_effort"] = "low"
            payload["include_reasoning"] = False
        if json_schema is not None:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "structured_output", "schema": json_schema}}
        if tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": tool.name, "description": tool.description, "parameters": tool.parameters}} for tool in tools]
            payload["parallel_tool_calls"] = False
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = Request(self.base_url + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
                          headers=headers, method="POST")
        result, attempts = resilience.send(self.provider, request, policy)
        try:
            choice = result["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ProviderUnavailable("incomplete_response", attempts=attempts, provider=self.provider)
            message = choice["message"]
            calls = [ToolCall(id=call["id"], name=call["function"]["name"],
                              arguments=json.loads(call["function"].get("arguments") or "{}"))
                     for call in message.get("tool_calls") or []]
            raw = result.get("usage") or {}
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
            raise ProviderUnavailable("invalid_response", attempts=attempts, provider=self.provider) from error
        if self.provider == "local":
            usage = raw
        else:
            usage = resilience.remote_usage(raw.get("prompt_tokens"), raw.get("completion_tokens"),
                                            raw.get("total_tokens"), attempts)
        return ChatResult(content=message.get("content") or None, tool_calls=calls, usage=usage,
                          provider=self.provider, model=self.model)


def _message(message):
    role = message["role"]
    if role == "assistant":
        converted = {"role": "assistant", "content": message.get("content")}
        if message.get("tool_calls"):
            converted["tool_calls"] = [{"id": call.id, "type": "function", "function": {
                "name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}
                for call in message["tool_calls"]]
        return converted
    if role == "tool":
        return {"role": "tool", "tool_call_id": message["tool_call_id"], "content": message["content"]}
    return {"role": role, "content": message["content"]}
