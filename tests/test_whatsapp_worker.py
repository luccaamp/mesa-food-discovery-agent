"""WhatsApp worker with an in-memory Redis and a recording client; no network."""

import json
import logging
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

try:
    import fakeredis
except ImportError as error:  # pragma: no cover - optional extra
    raise unittest.SkipTest("Install .[channels,test] to run WhatsApp worker tests") from error

from meal_discovery.channels.whatsapp import (DEAD_LETTER, STREAM, ConversationStore, SendFailed, WhatsAppClient,
                                              Worker, format_reply, user_key)

PHONE = "16505551234"
ITEM = {"vendor_id": "v1", "product_id": "p1", "name": "Chicken Rice", "unit_price": 0.004, "primary_cuisine": "chinese"}


class RecordingClient:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def send(self, to, text, buttons=None):
        if self.fail:
            raise self.fail
        self.sent.append((to, text, buttons))


class EchoAgent:
    """Records requests and returns a grounded response that updates the context."""

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        context = request.context.model_dump()
        context["last_query"] = "chicken rice"
        return {"answer": "Encontrei opções de arroz com frango.", "items": [ITEM], "context": context,
                "fallback_reason": None}


def enqueue(redis, text, message_id="wamid.1", phone=PHONE):
    payload = json.dumps({"message_id": message_id, "from": phone, "text": text, "timestamp": "1"})
    return redis.xadd(STREAM, {"payload": payload})


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis()
        self.agent, self.client = EchoAgent(), RecordingClient()
        self.worker = Worker(self.redis, self.agent, self.client)
        self.worker.ensure_group()
        self.worker.ensure_group()  # idempotent

    def test_message_is_answered_context_kept_and_queue_cleared(self):
        enqueue(self.redis, "Quero arroz com frango")
        self.assertEqual(self.worker.run_once(block_ms=10), ["ok"])
        to, text, buttons = self.client.sent[0]
        self.assertEqual(to, PHONE)
        self.assertIn("1. Chicken Rice · chinese · $$ · mais barato que 51% dos itens de chinese", text)
        self.assertEqual(buttons, ["Me recomende algo", "Nova busca"])
        self.assertEqual(self.redis.xlen(STREAM), 0)  # processed entries are deleted
        self.assertEqual(ConversationStore(self.redis).load(PHONE).last_query, "chicken rice")
        enqueue(self.redis, "até 0,005", "wamid.2")
        self.worker.run_once(block_ms=10)
        self.assertEqual(self.agent.requests[1].context.last_query, "chicken rice")

    def test_context_expires_and_keys_never_contain_the_phone(self):
        enqueue(self.redis, "Quero arroz com frango")
        self.worker.run_once(block_ms=10)
        keys = [key.decode() for key in self.redis.keys("*")]
        self.assertFalse(any(PHONE in key for key in keys))
        context_key = next(key for key in keys if key.startswith("mesa:ctx:"))
        self.assertTrue(0 < self.redis.ttl(context_key) <= 24 * 3600)

    def test_user_can_erase_their_data(self):
        enqueue(self.redis, "Quero arroz com frango")
        self.worker.run_once(block_ms=10)
        enqueue(self.redis, "Quero apagar meus dados", "wamid.2")
        self.worker.run_once(block_ms=10)
        self.assertEqual(self.redis.keys("mesa:ctx:*"), [])
        self.assertIn("apaguei", self.client.sent[-1][1])
        self.assertIsNone(self.client.sent[-1][2])
        self.assertEqual(len(self.agent.requests), 1)  # erasure never reaches the model

    def test_failures_go_to_dead_letter_without_personal_data(self):
        worker = Worker(self.redis, self.agent, RecordingClient(fail=SendFailed("http_401")))
        enqueue(self.redis, "Quero arroz com frango")
        with self.assertLogs("meal_discovery.whatsapp", level="INFO") as logs:
            self.assertEqual(worker.run_once(block_ms=10), ["send_http_401"])
        entry = self.redis.xrange(DEAD_LETTER)[0][1]
        self.assertEqual(set(entry), {b"entry", b"error"})
        self.assertNotIn(PHONE, json.dumps({k.decode(): v.decode() for k, v in entry.items()}))
        self.assertNotIn(PHONE, " ".join(logs.output))
        self.assertIn(user_key(PHONE)[:12], " ".join(logs.output))
        self.assertEqual(self.redis.xlen(STREAM), 0)

    def test_agent_crash_does_not_stop_the_batch(self):
        def broken(request):
            raise RuntimeError("boom")
        worker = Worker(self.redis, broken, self.client)
        enqueue(self.redis, "a", "wamid.1")
        enqueue(self.redis, "b", "wamid.2")
        self.assertEqual(worker.run_once(block_ms=10), ["error_RuntimeError", "error_RuntimeError"])
        self.assertEqual(self.redis.xlen(DEAD_LETTER), 2)


class FormattingAndClientTests(unittest.TestCase):
    def test_reply_lists_items_with_disclosure_and_fallback_notice(self):
        text = format_reply({"answer": "Achei.", "items": [ITEM, {**ITEM, "name": "Zero", "unit_price": 0}],
                             "fallback_reason": "quota"})
        self.assertIn("2. Zero · chinese · preço não informado", text)
        self.assertIn("não publica moeda", text)
        self.assertIn("glossário", text)
        self.assertEqual(format_reply({"answer": "Qual prato?", "items": []}), "Qual prato?")

    def test_client_builds_graph_api_requests_and_retries_only_server_errors(self):
        client = WhatsAppClient(token="t", phone_number_id="106540352242922", version="v23.0")
        with patch("meal_discovery.channels.whatsapp.urlopen", return_value=BytesIO(b'{"messages":[{"id":"x"}]}')) as transport:
            client.send(PHONE, "Olá", ["Me recomende algo"])
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, "https://graph.facebook.com/v23.0/106540352242922/messages")
        self.assertEqual(request.get_header("Authorization"), "Bearer t")
        body = json.loads(request.data)
        self.assertEqual(body["interactive"]["action"]["buttons"][0]["reply"]["title"], "Me recomende algo")
        with patch("meal_discovery.channels.whatsapp.urlopen",
                   side_effect=HTTPError("u", 401, "unauthorized", {}, None)) as transport, \
                patch("meal_discovery.channels.whatsapp.time.sleep"):
            with self.assertRaises(SendFailed):
                client.send(PHONE, "x")
        self.assertEqual(transport.call_count, 1)
        with patch("meal_discovery.channels.whatsapp.urlopen",
                   side_effect=[HTTPError("u", 503, "busy", {}, None), BytesIO(b"{}")]) as transport, \
                patch("meal_discovery.channels.whatsapp.time.sleep"):
            client.send(PHONE, "x")
        self.assertEqual(transport.call_count, 2)


if __name__ == "__main__":
    unittest.main()
