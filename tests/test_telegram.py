"""Telegram channel: routing, privacy, polling and client payloads; no network."""

from io import BytesIO
import json
import threading
import unittest
from unittest.mock import patch

try:
    import fakeredis
except ImportError as error:  # pragma: no cover
    raise unittest.SkipTest("Install .[channels,test] to run channel tests") from error

from meal_discovery.channels.telegram import MemoryKV, TelegramClient, poll, to_message
from meal_discovery.channels.whatsapp import STREAM, Worker
from test_whatsapp_worker import EchoAgent, RecordingClient, enqueue

UPDATE = {"update_id": 902345611, "message": {"message_id": 17, "date": 1794441000,
          "chat": {"id": 5551234, "type": "private"}, "text": "Quero arroz com frango"}}


class TelegramRoutingTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis()
        self.whatsapp, self.telegram, self.agent = RecordingClient(), RecordingClient(), EchoAgent()
        self.worker = Worker(self.redis, self.agent, self.whatsapp, telegram=self.telegram)
        self.worker.ensure_group()

    def test_each_message_is_answered_on_its_own_channel(self):
        self.redis.xadd(STREAM, {"payload": json.dumps({"channel": "telegram", "message_id": "tg:1", "from": "5551234",
                                                         "text": "Quero arroz com frango"})})
        enqueue(self.redis, "Quero arroz com frango", "wamid.9")
        self.assertEqual(self.worker.run_once(block_ms=10), ["ok", "ok"])
        self.assertEqual(self.telegram.sent[0][0], "5551234")
        self.assertNotIn("_Preços", self.telegram.sent[0][1])  # no WhatsApp markdown on Telegram
        self.assertIn("_Preços", self.whatsapp.sent[0][1])
        keys = [key.decode() for key in self.redis.keys("mesa:ctx:*")]
        self.assertEqual(len(keys), 2)  # same id on two channels never shares context
        self.assertFalse(any("5551234" in key for key in keys))

    def test_start_command_greets_without_calling_the_agent(self):
        handled = self.worker.handle({"channel": "telegram", "from": "1", "text": "/start"})
        self.assertIn("Mesa", handled.reply)
        self.assertEqual(self.agent.requests, [])

    def test_missing_channel_client_goes_to_dead_letter(self):
        worker = Worker(self.redis, self.agent, self.whatsapp)  # no Telegram client configured
        self.redis.xadd(STREAM, {"payload": json.dumps({"channel": "telegram", "message_id": "tg:2", "from": "1",
                                                         "text": "pizza"})})
        self.assertEqual(worker.run_once(block_ms=10), ["send_no_client_telegram"])


class PollingAndClientTests(unittest.TestCase):
    def test_only_private_text_messages_are_accepted(self):
        self.assertEqual(to_message(UPDATE)["from"], "5551234")
        group = {**UPDATE, "message": {**UPDATE["message"], "chat": {"id": 1, "type": "group"}}}
        self.assertIsNone(to_message(group))
        self.assertIsNone(to_message({"update_id": 3, "edited_message": {"text": "x"}}))

    def test_memory_store_expires(self):
        now = [0.0]
        store = MemoryKV(clock=lambda: now[0])
        store.set("k", "v", ex=10)
        self.assertEqual(store.get("k"), "v")
        now[0] = 11
        self.assertIsNone(store.get("k"))

    def test_poll_answers_and_advances_the_offset(self):
        stop = threading.Event()

        class FakeTelegram(RecordingClient):
            def __init__(self):
                super().__init__()
                self.calls = []

            def call(self, method, payload, timeout=15):
                self.calls.append((method, payload))
                if method == "getUpdates":
                    if payload["offset"] is None:
                        return [UPDATE]
                    stop.set()
                    return []
                return True

        client = FakeTelegram()
        worker = Worker(MemoryKV(), EchoAgent(), telegram=client)
        poll(worker, client, stop=stop, timeout=1)
        self.assertEqual(client.calls[0][0], "deleteWebhook")
        self.assertEqual(client.sent[0][0], "5551234")
        self.assertIn("Chicken Rice", client.sent[0][1])
        offsets = [payload["offset"] for method, payload in client.calls if method == "getUpdates"]
        self.assertEqual(offsets, [None, 902345612])

    def test_send_builds_bot_api_request_with_reply_keyboard(self):
        client = TelegramClient(token="123:abc")
        with patch("meal_discovery.channels.telegram.urlopen",
                   return_value=BytesIO(b'{"ok":true,"result":{"message_id":1}}')) as transport:
            client.send("5551234", "Olá", ["Me recomende algo", "Nova busca"])
        request = transport.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/bot123:abc/sendMessage"))
        body = json.loads(request.data)
        self.assertEqual(body["chat_id"], 5551234)
        self.assertEqual(body["reply_markup"]["keyboard"][0][0]["text"], "Me recomende algo")


if __name__ == "__main__":
    unittest.main()
