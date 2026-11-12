"""WhatsApp channel: consume queued messages, run the agent, reply.

The Go gateway verifies, de-duplicates and queues webhooks on a Redis Stream.
This worker reads them through a consumer group, keeps each conversation's
context, runs the same agent as the web app and answers through the WhatsApp
Cloud API.

Privacy by design (LGPD):
- phone numbers are never logged; logs and keys use a salted hash;
- conversation context expires after 24 hours of inactivity;
- processed queue entries are deleted, and the dead-letter queue keeps only
  the message ID and an error class, never text or phone;
- the user can type "apagar meus dados" to erase their context immediately.
"""

from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..api_models import AssistantContext, AssistantRequest
from ..discovery import fold
from ..pricing import describe, price_band

logger = logging.getLogger("meal_discovery.whatsapp")

STREAM = "mesa:inbound"
GROUP = "mesa-agent"
DEAD_LETTER = "mesa:dead-letter"
CONTEXT_TTL_SECONDS = 24 * 3600
GRAPH_API = os.environ.get("WHATSAPP_GRAPH_URL", "https://graph.facebook.com") + "/{version}/{phone_number_id}/messages"
ERASE = re.compile(r"(?:apagar|excluir|deletar) (?:meus )?dados|delete my data|forget me")
BUTTONS = ["Me recomende algo", "Nova busca"]


def user_key(phone: str) -> str:
    salt = os.environ.get("MESA_PRIVACY_SALT", "mesa-development-salt")
    return hashlib.sha256((salt + phone).encode()).hexdigest()[:32]


class ConversationStore:
    """Per-user AssistantContext in Redis with an inactivity TTL."""

    def __init__(self, redis, ttl=CONTEXT_TTL_SECONDS):
        self.redis, self.ttl = redis, ttl

    def _key(self, phone):
        return "mesa:ctx:" + user_key(phone)

    def load(self, phone) -> AssistantContext:
        raw = self.redis.get(self._key(phone))
        if not raw:
            return AssistantContext()
        try:
            return AssistantContext.model_validate_json(raw)
        except ValueError:
            return AssistantContext()

    def save(self, phone, context: AssistantContext):
        self.redis.set(self._key(phone), context.model_dump_json(), ex=self.ttl)

    def forget(self, phone):
        self.redis.delete(self._key(phone))


def format_reply(response, channel="whatsapp") -> str:
    """Plain-text chat message: the grounded answer plus up to five items."""
    italic = (lambda s: f"_{s}_") if channel == "whatsapp" else (lambda s: s)
    lines = [response["answer"]]
    for index, item in enumerate(response.get("items", [])[:5], start=1):
        band = item.get("price_band") or price_band(item.get("unit_price"), item.get("primary_cuisine"))
        lines.append(f"{index}. {item['name']} · {item['primary_cuisine']} · {describe(band)}")
    if response.get("items"):
        lines.append(italic("Preço em faixas dentro de cada culinária ($ barato, $$ médio, $$$ mais caro): "
                            "a base não publica moeda. Nomes não garantem ingredientes."))
    if response.get("fallback_reason"):
        lines.append(italic("IA indisponível agora: usei o glossário do catálogo."))
    return "\n".join(lines)[:4000]


class WhatsAppClient:
    def __init__(self, token=None, phone_number_id=None, version=None):
        self.token = token if token is not None else os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self.version = version or os.environ.get("WHATSAPP_API_VERSION", "v23.0")

    @property
    def configured(self):
        return bool(self.token and self.phone_number_id)

    def send(self, to: str, text: str, buttons=None):
        if buttons:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": {
                "type": "button", "body": {"text": text[:1024]},
                "action": {"buttons": [{"type": "reply", "reply": {"id": f"b{i}", "title": title[:20]}}
                                       for i, title in enumerate(buttons[:3])]}}}
            if len(text) > 1024:  # interactive bodies are short; fall back to text
                payload = None
        else:
            payload = None
        if payload is None:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
                       "text": {"body": text[:4096], "preview_url": False}}
        request = Request(GRAPH_API.format(version=self.version, phone_number_id=self.phone_number_id),
                          data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        for attempt in range(2):
            try:
                with urlopen(request, timeout=15) as response:
                    return json.load(response)
            except HTTPError as error:
                code = error.code
                error.close()
                if code < 500 or attempt == 1:
                    raise SendFailed(f"http_{code}") from None
            except (URLError, TimeoutError, OSError):
                if attempt == 1:
                    raise SendFailed("network") from None
            time.sleep(1)


class SendFailed(Exception):
    pass


@dataclass
class Handled:
    reply: str
    erased: bool = False


WELCOME = ("Olá! Sou o assistente do Mesa, com 1,7 milhão de pedidos reais de delivery de Singapura. "
           "Diga onde você está e eu mostro o que mais se pede ali agora, por exemplo \"estou em Tampines\". "
           "Depois peça o que tiver vontade: \"comida japonesa barata\".")


def identity(message):
    """Conversation key: WhatsApp keeps the bare number (hashed); other channels are namespaced."""
    channel = message.get("channel", "whatsapp")
    return message["from"] if channel == "whatsapp" else f"{channel}:{message['from']}"


class Worker:
    """Consumes the shared inbound stream and answers on the channel each message came from."""

    def __init__(self, redis, agent, client=None, *, telegram=None, consumer="worker-1"):
        self.redis, self.agent, self.client = redis, agent, client
        self.clients = {"whatsapp": client, "telegram": telegram}
        self.store = ConversationStore(redis)
        self.consumer = consumer

    def ensure_group(self):
        try:
            self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except Exception as error:  # BUSYGROUP: already exists
            if "BUSYGROUP" not in str(error):
                raise

    def handle(self, message: dict) -> Handled:
        user, text, channel = identity(message), message["text"], message.get("channel", "whatsapp")
        if text.strip().lower() in {"/start", "/help"}:
            return Handled(WELCOME)
        if ERASE.search(fold(text)):
            self.store.forget(user)
            return Handled("Pronto: apaguei o contexto da nossa conversa. Nenhum histórico seu fica guardado.", True)
        context = self.store.load(user)
        response = self.agent(AssistantRequest(message=text[:500], context=context))
        from ..observability import record_turn
        record_turn(channel, response)
        self.store.save(user, AssistantContext.model_validate(response["context"]))
        return Handled(format_reply(response, channel))

    def process(self, entry_id, fields):
        started = time.perf_counter()
        user, outcome = "unknown", "ok"
        try:
            message = json.loads(fields[b"payload"] if b"payload" in fields else fields["payload"])
            channel = message.get("channel", "whatsapp")
            user = user_key(identity(message))[:12]
            client = self.clients.get(channel)
            if client is None:
                raise SendFailed("no_client_" + channel)
            handled = self.handle(message)
            client.send(message["from"], handled.reply, None if handled.erased else BUTTONS)
        except SendFailed as error:
            outcome = "send_" + str(error)
            self.redis.xadd(DEAD_LETTER, {"entry": entry_id, "error": outcome}, maxlen=500, approximate=True)
        except Exception as error:  # never let one message stop the worker
            outcome = "error_" + type(error).__name__
            self.redis.xadd(DEAD_LETTER, {"entry": entry_id, "error": outcome}, maxlen=500, approximate=True)
        finally:
            # Acknowledge and delete: processed messages are not retained.
            self.redis.xack(STREAM, GROUP, entry_id)
            self.redis.xdel(STREAM, entry_id)
            logger.info("whatsapp_message user=%s outcome=%s elapsed_ms=%d", user, outcome,
                        round((time.perf_counter() - started) * 1000))
        return outcome

    def run_once(self, block_ms=5000, count=10):
        batches = self.redis.xreadgroup(GROUP, self.consumer, {STREAM: ">"}, count=count, block=block_ms) or []
        outcomes = []
        for _stream, entries in batches:
            for entry_id, fields in entries:
                outcomes.append(self.process(entry_id, fields))
        return outcomes

    def run_forever(self, stop=None):
        self.ensure_group()
        while not (stop and stop.is_set()):
            try:
                self.run_once()
            except Exception as error:
                logger.warning("whatsapp_worker_loop reason=%s", type(error).__name__)
                time.sleep(2)


def build_from_environment(reader, recommender):
    """Create a worker bound to the given catalog tools, or None when not configured."""
    url = os.environ.get("REDIS_URL")
    from .telegram import TelegramClient
    client, telegram = WhatsAppClient(), TelegramClient()
    if not url or not (client.configured or telegram.configured):
        return None
    import redis
    from ..agent import run_agent
    return Worker(redis.Redis.from_url(url), lambda request: run_agent(request, reader, recommender),
                  client if client.configured else None, telegram=telegram if telegram.configured else None,
                  consumer=os.environ.get("WORKER_NAME", "worker-1"))
