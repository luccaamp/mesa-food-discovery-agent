"""Google Gemini adapter (Generative Language API, key sent only in a header)."""

import json
import os
import re
from urllib.request import Request

from . import resilience
from .types import ChatResult, ProviderUnavailable, ToolCall

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODEL_PATTERN = re.compile(r"gemini-[A-Za-z0-9._-]{1,100}")


class GeminiChatModel:
    provider = "gemini"

    def __init__(self, model=None, key=None):
        self.model = model or os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
        self.key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")

    @property
    def configured(self):
        return bool(self.key and self.model)

    def chat(self, messages, *, tools=None, json_schema=None, max_tokens=256, temperature=0.0):
        if not self.configured:
            raise ProviderUnavailable("not_configured", provider=self.provider)
        if not MODEL_PATTERN.fullmatch(self.model):
            raise ProviderUnavailable("invalid_model_configuration", provider=self.provider)
        policy = resilience.budget_policy(self.provider)
        payload = {"contents": _contents(messages),
                   "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_schema is not None:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseJsonSchema"] = json_schema
        if tools:
            payload["tools"] = [{"functionDeclarations": [
                {"name": tool.name, "description": tool.description, "parametersJsonSchema": tool.parameters}
                for tool in tools]}]
        if self.model.startswith("gemini-2.5-flash"):
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        elif re.match(r"gemini-3", self.model):
            payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "minimal"}
        request = Request(ENDPOINT.format(model=self.model), data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json", "x-goog-api-key": self.key}, method="POST")
        result, attempts = resilience.send(self.provider, request, policy)
        try:
            candidate = result["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ProviderUnavailable("incomplete_response", attempts=attempts, provider=self.provider)
            parts = candidate["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
            calls = []
            for index, part in enumerate(parts):
                if "functionCall" in part:
                    call = part["functionCall"]
                    extra = {"thought_signature": part["thoughtSignature"]} if part.get("thoughtSignature") else {}
                    calls.append(ToolCall(id=call.get("id") or f"call_{index}", name=call["name"],
                                          arguments=dict(call.get("args") or {}), extra=extra))
            raw = result.get("usageMetadata", {})
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ProviderUnavailable("invalid_response", attempts=attempts, provider=self.provider) from error
        usage = resilience.remote_usage(raw.get("promptTokenCount"), raw.get("candidatesTokenCount"),
                                        raw.get("totalTokenCount"), attempts,
                                        thought_tokens=raw.get("thoughtsTokenCount", 0))
        return ChatResult(content=text or None, tool_calls=calls, usage=usage,
                          provider=self.provider, model=self.model)


def _contents(messages):
    contents = []
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": message["content"]}]})
        elif role == "assistant":
            parts = [{"text": message["content"]}] if message.get("content") else []
            for call in message.get("tool_calls") or []:
                part = {"functionCall": {"name": call.name, "args": call.arguments}}
                if call.extra.get("thought_signature"):
                    part["thoughtSignature"] = call.extra["thought_signature"]
                parts.append(part)
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            response = {"name": message["name"], "response": {"result": message["content"]}}
            # Consecutive tool results belong to the same user turn.
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append({"functionResponse": response})
            else:
                contents.append({"role": "user", "parts": [{"functionResponse": response}]})
    return contents
