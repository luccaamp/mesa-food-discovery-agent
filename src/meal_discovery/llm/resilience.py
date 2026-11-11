"""Bounded, quota-aware HTTP transport shared by every remote LLM adapter.

Each provider gets its own call budget and outage cooldown. A request makes at
most `max_attempts` attempts inside a total time budget; transient HTTP errors
and one timeout are retried, quota and authentication errors never are. Every
attempt is charged to the local budget because an interrupted attempt may still
be billed upstream. These limits are process-local; provider quotas remain the
final authority.
"""

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import json
import logging
import os
from time import monotonic, perf_counter, sleep, time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from ..cloud_limits import CallBudget, ProviderCooldown
from .types import ProviderUnavailable

logger = logging.getLogger("meal_discovery.llm")

TRANSIENT_HTTP = {500, 502, 503, 504}
MAX_RESPONSE_BYTES = 256 * 1024
USER_AGENT = "mesa-food-discovery-agent/0.9"
BUDGETS: dict[str, CallBudget] = {}
COOLDOWNS: dict[str, ProviderCooldown] = {}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    attempt_timeout: float = 20
    total_timeout: float = 45
    per_minute: int | None = None  # None disables the local budget (loopback models)
    per_day: int | None = None


DEFAULT_BUDGETS = {"gemini": (4, 20), "groq": (20, 500), "openai": (4, 20)}


def budget_policy(provider):
    """Read `<PROVIDER>_CALLS_PER_MINUTE/DAY`; invalid values never send a request."""
    minute_default, day_default = DEFAULT_BUDGETS.get(provider, (4, 20))
    prefix = provider.upper()
    try:
        minute = int(os.environ.get(f"{prefix}_CALLS_PER_MINUTE", str(minute_default)))
        daily = int(os.environ.get(f"{prefix}_CALLS_PER_DAY", str(day_default)))
        if not 1 <= minute <= 60 or not 1 <= daily <= 10_000:
            raise ValueError()
    except ValueError as error:
        raise ProviderUnavailable("invalid_budget_configuration", provider=provider) from error
    return RetryPolicy(per_minute=minute, per_day=daily)


def budget(provider):
    return BUDGETS.setdefault(provider, CallBudget())


def cooldown(provider):
    return COOLDOWNS.setdefault(provider, ProviderCooldown())


def retry_delay(headers):
    """Honor both Retry-After forms; never shorten a server-requested delay."""
    value = (headers or {}).get("Retry-After", "")
    if not isinstance(value, str):
        return 1
    value = value.strip()
    if value.isdigit():
        return max(1, int(value)) if len(value) <= 6 else float("inf")
    if value:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is not None:
                return max(1, date.timestamp() - time())
        except (TypeError, ValueError, OverflowError):
            pass
    return 1


def network_failure_reason(error):
    cause = error.reason if isinstance(error, URLError) else error
    return "provider_timeout" if isinstance(cause, TimeoutError) else "network_error"


def send(provider, request, policy: RetryPolicy):
    """Send one logical request through the provider's cooldown and budget."""
    # Some providers sit behind bot protection that rejects urllib's default agent.
    if not request.has_header("User-agent"):
        request.add_header("User-Agent", USER_AGENT)
    state = cooldown(provider)
    if not state.acquire():
        raise ProviderUnavailable("provider_cooldown", provider=provider)
    outcome = "neutral"
    started = perf_counter()
    try:
        result = _attempts(provider, request, policy)
        outcome = "success"
        return result
    except ProviderUnavailable as error:
        error.provider = provider
        if error.reason in {"provider_timeout", "network_error",
                            *(f"provider_http_{code}" for code in TRANSIENT_HTTP)}:
            outcome = "failure"
        logger.warning("llm_request provider=%s reason=%s attempts=%d elapsed_ms=%d",
                       provider, error.reason, error.attempts, round((perf_counter() - started) * 1000))
        raise
    finally:
        state.record(outcome)


def _attempts(provider, request, policy):
    deadline = monotonic() + policy.total_timeout
    attempts = 0
    for number in range(1, policy.max_attempts + 1):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ProviderUnavailable("provider_timeout", attempts=attempts)
        if policy.per_minute is not None and not budget(provider).take(policy.per_minute, policy.per_day):
            raise ProviderUnavailable("local_quota", attempts=attempts)
        attempts = number
        try:
            with urlopen(request, timeout=min(policy.attempt_timeout, remaining)) as response:
                return json.loads(response.read(MAX_RESPONSE_BYTES)), attempts
        except HTTPError as error:
            delay = retry_delay(error.headers)
            code = error.code
            if error.fp is not None:
                error.close()
            if code not in TRANSIENT_HTTP or number == policy.max_attempts or delay >= deadline - monotonic():
                raise ProviderUnavailable(f"provider_http_{code}", attempts=attempts) from error
            logger.info("llm_retry provider=%s attempt=%d reason=provider_http_%d delay_ms=%d",
                        provider, number, code, round(delay * 1000))
            sleep(delay)
        except (URLError, TimeoutError, OSError) as error:
            reason = network_failure_reason(error)
            if (reason != "provider_timeout" or number == policy.max_attempts
                    or deadline - monotonic() < policy.attempt_timeout + 1):
                raise ProviderUnavailable(reason, attempts=attempts) from error
            logger.info("llm_retry provider=%s attempt=%d reason=provider_timeout delay_ms=1000", provider, number)
            sleep(1)
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable("invalid_response", attempts=attempts) from error
    raise AssertionError("Unreachable bounded retry state")


def remote_usage(prompt, completion, total, attempts, **extra):
    """Token counts of the successful response only; failed attempts stay unknown."""
    return {"prompt_tokens": prompt or 0, "completion_tokens": completion or 0, "total_tokens": total or 0,
            **extra, "provider_attempts": attempts, "failed_attempts_usage_unknown": attempts - 1}
