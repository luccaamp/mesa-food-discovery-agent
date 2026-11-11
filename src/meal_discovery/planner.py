"""Intent planning: one structured LLM call that maps a message to a bounded action.

The planner only chooses an allowed action and English catalog keywords. Items,
prices and explanations always come from the catalog, never from the model.
"""

from importlib.resources import files
import json

from pydantic import ValidationError

from .api_models import IntentPlan
from .llm import ProviderUnavailable, from_environment

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["search_catalog", "recommend_items", "clarify"]},
        "query": {"type": ["string", "null"]},
    },
    "required": ["action", "query"],
    "additionalProperties": False,
}


def prompt_text():
    return files("meal_discovery").joinpath("prompts/intent_v1.txt").read_text(encoding="utf-8")


class IntentPlanner:
    def __init__(self, chat_model=None):
        self.chat_model = chat_model if chat_model is not None else from_environment()
        self.provider = self.chat_model.provider if self.chat_model else "disabled"
        self.model = self.chat_model.model if self.chat_model else None
        self.last_served = None

    @property
    def configured(self):
        return bool(self.chat_model and self.chat_model.configured)

    def plan(self, message, context):
        if self.chat_model is None:
            raise ProviderUnavailable("provider_disabled", provider=self.provider)
        user = json.dumps({"message": message, "previous_query": context.last_query}, ensure_ascii=False)
        result = self.chat_model.chat([{"role": "system", "content": prompt_text()},
                                       {"role": "user", "content": user}],
                                      json_schema=PLAN_SCHEMA, max_tokens=512, temperature=0.0)
        try:
            plan = IntentPlan.model_validate_json(result.content or "")
        except (ValidationError, ValueError) as error:
            raise ProviderUnavailable("invalid_response", provider=result.provider,
                                      attempts=result.usage.get("provider_attempts", 1)) from error
        self.last_served = (result.provider, result.model)
        return plan, result.usage
