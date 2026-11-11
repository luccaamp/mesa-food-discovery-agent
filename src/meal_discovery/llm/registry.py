"""Build chat models from configuration and route across providers.

Configuration (environment):
  LLM_PROVIDER            primary provider: gemini | groq | local | openai | disabled
  LLM_MODEL               model for the primary provider (optional)
  LLM_FALLBACK_PROVIDERS  comma-separated providers tried in order when the
                          primary fails (for example "groq")
"""

import os

from .gemini import GeminiChatModel
from .openai_compatible import OpenAICompatibleChatModel
from . import resilience
from .types import ChatResult, ProviderUnavailable

KNOWN = ("gemini", "groq", "local", "openai")


def build(provider, model=None):
    if provider == "gemini":
        return GeminiChatModel(model=model)
    if provider in ("groq", "local", "openai"):
        return OpenAICompatibleChatModel(provider, model=model)
    raise ProviderUnavailable("provider_disabled", provider=provider)


class FallbackChatModel:
    """Try providers in order. The first valid answer wins.

    A provider that fails (timeout, cooldown, quota, invalid output) does not
    end the request while another configured provider remains. If every
    provider fails, the primary provider's sanitized reason is raised, because
    it describes the configured default path.
    """

    def __init__(self, models):
        if not models:
            raise ValueError("At least one chat model is required")
        self.models = models
        self.provider = models[0].provider
        self.model = models[0].model

    @property
    def configured(self):
        return any(model.configured for model in self.models)

    def chat(self, messages, **options) -> ChatResult:
        failures = []
        for model in self.models:
            if not model.configured:
                continue
            try:
                result = model.chat(messages, **options)
                if failures:
                    result.usage = {**result.usage, "fallback_from": [
                        {"provider": error.provider, "reason": error.reason, "attempts": error.attempts}
                        for error in failures]}
                return result
            except ProviderUnavailable as error:
                error.provider = error.provider or model.provider
                failures.append(error)
        if not failures:
            raise ProviderUnavailable("not_configured", provider=self.provider)
        primary = failures[0]
        raise ProviderUnavailable(primary.reason, provider=primary.provider,
                                  attempts=sum(error.attempts for error in failures))


def from_environment():
    primary = os.environ.get("LLM_PROVIDER", "local")
    if primary not in KNOWN:
        return None
    models = [build(primary, os.environ.get("LLM_MODEL") or None)]
    for name in os.environ.get("LLM_FALLBACK_PROVIDERS", "").split(","):
        name = name.strip()
        if name in KNOWN and name not in {model.provider for model in models}:
            models.append(build(name))
    return models[0] if len(models) == 1 else FallbackChatModel(models)


def describe(chat_model):
    """Sanitized provider status for operations endpoints (never keys)."""
    models = chat_model.models if isinstance(chat_model, FallbackChatModel) else [chat_model]
    described = []
    for model in models:
        entry = {"provider": model.provider, "model": model.model, "configured": model.configured}
        if model.provider != "local":
            entry["cooldown"] = resilience.cooldown(model.provider).snapshot()
        described.append(entry)
    return described
