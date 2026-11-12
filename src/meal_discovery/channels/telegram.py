"""Telegram channel for the same Mesa agent.

Two ways to run it:
- production: Telegram -> webhook on the Go gateway (/telegram, secret header)
  -> Redis Stream -> the shared worker, exactly like WhatsApp;
- local demo: `python -m meal_discovery.channels.telegram` uses long polling,
  so it works from a laptop without a public URL or Redis.

Privacy rules are the same as WhatsApp: chat IDs are only stored as salted
hashes, context expires after 24 h and "apagar meus dados" erases it.
"""

import argparse
import json
import logging
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("meal_discovery.telegram")


def api_base():
    return os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org")


class TelegramClient:
    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")

    @property
    def configured(self):
        return bool(self.token)

    def call(self, method, payload, timeout=15):
        request = Request(f"{api_base()}/bot{self.token}/{method}", data=json.dumps(payload).encode(),
                          method="POST", headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)["result"]

    def send(self, chat_id, text, buttons=None):
        from .whatsapp import SendFailed
        payload = {"chat_id": int(chat_id), "text": text[:4096], "link_preview_options": {"is_disabled": True}}
        if buttons:
            payload["reply_markup"] = {"keyboard": [[{"text": title}] for title in buttons],
                                       "resize_keyboard": True, "one_time_keyboard": True}
        else:
            payload["reply_markup"] = {"remove_keyboard": True}
        for attempt in range(2):
            try:
                return self.call("sendMessage", payload)
            except HTTPError as error:
                code = error.code
                error.close()
                if code < 500 and code != 429 or attempt == 1:
                    raise SendFailed(f"http_{code}") from None
            except (URLError, TimeoutError, OSError):
                if attempt == 1:
                    raise SendFailed("network") from None
            time.sleep(1)


class MemoryKV:
    """Minimal in-process key-value store with expiry, for the polling demo."""

    def __init__(self, clock=time.monotonic):
        self.data, self.clock = {}, clock

    def get(self, key):
        value = self.data.get(key)
        if value and value[1] is not None and value[1] < self.clock():
            self.data.pop(key, None)
            return None
        return value[0] if value else None

    def set(self, key, value, ex=None):
        self.data[key] = (value, self.clock() + ex if ex else None)

    def delete(self, key):
        self.data.pop(key, None)


def to_message(update):
    """Private text messages only; everything else is ignored."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    if chat.get("type") != "private" or not text:
        return None
    return {"channel": "telegram", "message_id": f"tg:{update['update_id']}", "from": str(chat["id"]),
            "text": text[:500], "timestamp": str(message.get("date", ""))}


def poll(worker, client, *, stop=None, timeout=25):
    """Long-polling loop: fetch updates, answer each with the shared worker logic."""
    from .whatsapp import BUTTONS, user_key
    client.call("deleteWebhook", {"drop_pending_updates": False})
    offset = None
    while not (stop and stop.is_set()):
        try:
            updates = client.call("getUpdates", {"timeout": timeout, "offset": offset, "allowed_updates": ["message"]},
                                  timeout=timeout + 10)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            logger.warning("telegram_poll reason=%s", type(error).__name__)
            time.sleep(3)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = to_message(update)
            if message is None:
                continue
            started = time.perf_counter()
            outcome = "ok"
            try:
                client.call("sendChatAction", {"chat_id": int(message["from"]), "action": "typing"})
                handled = worker.handle(message)
                client.send(message["from"], handled.reply, None if handled.erased else BUTTONS)
            except Exception as error:  # one bad message never stops the bot
                outcome = "error_" + type(error).__name__
            logger.info("telegram_message user=%s outcome=%s elapsed_ms=%d",
                        user_key("telegram:" + message["from"])[:12], outcome,
                        round((time.perf_counter() - started) * 1000))


def set_webhook(client, url, secret):
    """Point Telegram at the gateway; the secret comes back in every delivery header."""
    return client.call("setWebhook", {"url": url, "secret_token": secret, "allowed_updates": ["message"],
                                      "drop_pending_updates": True})


def main():
    parser = argparse.ArgumentParser(description="Run the Mesa Telegram bot with long polling (local demo).")
    parser.add_argument("--index", type=Path, default=Path(os.environ.get(
        "MEAL_CATALOG_INDEX", "data/processed/singapore-catalog-v1.sqlite")))
    parser.add_argument("--serving", type=Path, default=Path(os.environ.get(
        "MEAL_SERVING_INDEX", "data/processed/singapore-serving-v1.sqlite")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    client = TelegramClient()
    if not client.configured:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first")
    from ..agent import run_agent
    from ..api import CatalogReader
    from ..api_models import RecommendationParams
    from ..serving import recommend
    from .whatsapp import Worker
    reader = CatalogReader(args.index)

    def recommender(arguments):
        params = RecommendationParams.model_validate(arguments)
        return recommend(args.serving, [(s.vendor_id, s.product_id) for s in params.seeds], cuisine=params.cuisine,
                         min_price=params.min_price, max_price=params.max_price, limit=params.limit)

    worker = Worker(MemoryKV(), lambda request: run_agent(request, reader, recommender), telegram=client)
    me = client.call("getMe", {})
    print(f"Mesa no Telegram: https://t.me/{me['username']}  (Ctrl+C para parar)", flush=True)
    try:
        poll(worker, client)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
