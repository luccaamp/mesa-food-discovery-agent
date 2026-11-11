"""End-to-end check of the WhatsApp channel without a Meta account.

Runs the real pieces together: signed webhooks -> Go gateway binary -> Redis
Stream -> Python worker -> agent (real LLM + official catalog) -> a local
server that imitates the WhatsApp Graph API and records what would be sent.

Requires: Redis on REDIS_URL (e.g. `docker run -p 6379:6379 redis:7.4-alpine`),
Go, the catalog artifacts and an LLM key. The report stores no phone numbers.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SECRET, VERIFY, PHONE = "integration-secret", "integration-verify", "15550000001"


class GraphMock(BaseHTTPRequestHandler):
    sent = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        GraphMock.sent.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        payload = json.dumps({"messages": [{"id": f"wamid.out{len(GraphMock.sent)}"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def webhook(message_id, text):
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages",
        "value": {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "106540352242922"},
                  "messages": [{"from": PHONE, "id": message_id, "timestamp": str(int(time.time())),
                                "type": "text", "text": {"body": text}}]}}]}]}).encode()


def deliver(port, body, signature=None):
    signature = signature or "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    request = Request(f"http://127.0.0.1:{port}/webhook", data=body, method="POST",
                      headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
    except Exception as error:
        status = getattr(error, "code", 0)
    return status, round((time.perf_counter() - started) * 1000, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--redis", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new report path")

    graph = ThreadingHTTPServer(("127.0.0.1", 0), GraphMock)
    threading.Thread(target=graph.serve_forever, daemon=True).start()
    os.environ.update({"WHATSAPP_GRAPH_URL": f"http://127.0.0.1:{graph.server_port}", "WHATSAPP_ACCESS_TOKEN": "test-token",
                       "WHATSAPP_PHONE_NUMBER_ID": "106540352242922", "REDIS_URL": args.redis})

    import redis
    from meal_discovery.api import CatalogReader
    from meal_discovery.api_models import RecommendationParams
    from meal_discovery.channels import whatsapp
    from meal_discovery.serving import recommend
    store = redis.Redis.from_url(args.redis)
    for key in store.scan_iter("mesa:*"):
        store.delete(key)

    binary = Path(tempfile.gettempdir()) / ("mesa-gateway" + (".exe" if os.name == "nt" else ""))
    subprocess.run(["go", "build", "-o", str(binary), "."], cwd=ROOT / "services/whatsapp-gateway", check=True,
                   env={**os.environ, "CGO_ENABLED": "0"})
    port = 8097
    gateway = subprocess.Popen([str(binary)], env={**os.environ, "PORT": str(port), "WHATSAPP_APP_SECRET": SECRET,
                                                   "WHATSAPP_VERIFY_TOKEN": VERIFY},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = {"kind": "whatsapp_channel_integration", "created_at": datetime.now(timezone.utc).isoformat(),
              "components": ["go_gateway_binary", "redis_stream", "python_worker", "agent_real_llm", "graph_api_mock"],
              "phone_numbers_stored": False, "checks": {}}
    try:
        for _ in range(50):
            try:
                urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        with urlopen(f"http://127.0.0.1:{port}/webhook?hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=4242") as response:
            report["checks"]["verification_handshake"] = response.read() == b"4242"

        reader = CatalogReader(ROOT / "data/processed/singapore-catalog-v1.sqlite")
        serving = ROOT / "data/processed/singapore-serving-v1.sqlite"

        def recommender(arguments):
            params = RecommendationParams.model_validate(arguments)
            return recommend(serving, [(s.vendor_id, s.product_id) for s in params.seeds], cuisine=params.cuisine,
                             min_price=params.min_price, max_price=params.max_price, limit=params.limit)

        worker = whatsapp.build_from_environment(reader, recommender)
        worker.ensure_group()

        first = webhook("wamid.it1", "Quero arroz com frango")
        statuses = [deliver(port, first), deliver(port, first)]  # Meta retry -> duplicate
        report["checks"]["webhook_ack_ms"] = [ms for _, ms in statuses]
        report["checks"]["duplicate_acknowledged_once"] = [s for s, _ in statuses] == [200, 200]
        report["checks"]["tampered_rejected"] = deliver(port, webhook("wamid.bad", "x"), "sha256=" + "0" * 64)[0] == 401
        started = time.perf_counter()
        outcomes = worker.run_once(block_ms=2000)
        report["checks"]["first_turn_ms"] = round((time.perf_counter() - started) * 1000)
        report["checks"]["queued_once"] = outcomes == ["ok"]

        deliver(port, webhook("wamid.it2", "agora até 0,005"))
        outcomes += worker.run_once(block_ms=2000)
        deliver(port, webhook("wamid.it3", "apagar meus dados"))
        outcomes += worker.run_once(block_ms=2000)

        replies = [entry["body"] for entry in GraphMock.sent]
        texts = [reply.get("interactive", {}).get("body", {}).get("text") or reply.get("text", {}).get("body", "")
                 for reply in replies]
        report["checks"]["replies_sent"] = len(replies)
        report["checks"]["graph_api_auth_header"] = all(entry["auth"] == "Bearer test-token" for entry in GraphMock.sent)
        report["checks"]["first_reply_lists_catalog_items"] = "1. " in texts[0] and "u.n." in texts[0]
        report["checks"]["second_reply_keeps_dish_with_price_filter"] = "1. " in texts[1]
        report["checks"]["erasure_confirmed"] = "apaguei" in texts[2]
        report["checks"]["context_erased"] = not list(store.scan_iter("mesa:ctx:*"))
        report["checks"]["queue_empty_after_processing"] = store.xlen(whatsapp.STREAM) == 0
        report["checks"]["no_phone_in_redis_keys"] = not any(PHONE in key.decode() for key in store.scan_iter("*"))
        report["outcomes"] = outcomes
        report["replies"] = texts
        report["passed"] = all(value for key, value in report["checks"].items() if isinstance(value, bool))
    finally:
        gateway.terminate()
        graph.shutdown()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["checks"], indent=2, ensure_ascii=False))
    print("PASSED" if report["passed"] else "FAILED")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    main()
