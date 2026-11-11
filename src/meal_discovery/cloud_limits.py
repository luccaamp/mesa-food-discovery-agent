"""Small process-local limits for the public demo; provider quotas remain authoritative."""

from collections import deque
from threading import BoundedSemaphore, Lock
from time import monotonic, time

from starlette.responses import JSONResponse


class CallBudget:
    def __init__(self, *, clock=monotonic, wall_clock=time):
        self.clock, self.wall_clock = clock, wall_clock
        self.lock = Lock()
        self.calls = deque()
        self.day = None
        self.day_calls = 0

    def take(self, per_minute, per_day):
        with self.lock:
            now = self.clock()
            day = int(self.wall_clock() // 86400)
            if self.day != day:
                self.day, self.day_calls = day, 0
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) >= per_minute or self.day_calls >= per_day:
                return False
            self.calls.append(now)
            self.day_calls += 1
            return True


class ProviderCooldown:
    """Process-local outage protection, with one probe after the pause.

    This does not reset or replace the provider quota. A restart loses this
    transient state; the upstream quota remains authoritative.
    """

    def __init__(self, *, threshold=2, seconds=60, clock=monotonic):
        self.threshold, self.seconds, self.clock = threshold, seconds, clock
        self.lock = Lock()
        self.failures, self.until, self.probing = 0, 0.0, False
        self.inflight = 0

    def acquire(self):
        with self.lock:
            if self.clock() < self.until or self.probing:
                return False
            if self.failures >= self.threshold:
                # Earlier requests may still be completing. Do not let their
                # completion release a newer recovery probe's admission.
                if self.inflight:
                    return False
                self.probing = True
            self.inflight += 1
            return True

    def record(self, outcome):
        with self.lock:
            self.probing = False
            self.inflight = max(0, self.inflight - 1)
            if outcome == "success":
                self.failures, self.until = 0, 0.0
            elif outcome == "failure":
                self.failures += 1
                if self.failures >= self.threshold:
                    self.until = self.clock() + self.seconds

    def snapshot(self):
        with self.lock:
            remaining = max(0, self.until - self.clock())
            return {"paused": remaining > 0 or self.probing or (self.failures >= self.threshold and self.inflight > 0),
                    "retry_after_seconds": int(remaining) + (remaining % 1 > 0),
                    "consecutive_failures": self.failures}


class PublicDemoGuard:
    """Bounded body buffering and heavy-request admission before domain execution."""

    HEAVY = {"/v1/catalog/search", "/v1/discovery/search", "/v1/recommendations", "/v1/assistant"}

    def __init__(self, app, *, enabled=False, concurrency=4, requests_per_minute=60, body_bytes=8192):
        self.app, self.enabled = app, enabled
        self.capacity = BoundedSemaphore(concurrency)
        self.budget = CallBudget()
        self.requests_per_minute, self.body_bytes = requests_per_minute, body_bytes

    async def reject(self, scope, receive, send, status, code, message):
        request_id = scope.get("state", {}).get("request_id", "")
        response = JSONResponse({"error": {"code": code, "message": message, "request_id": request_id, "issues": []}},
                                status_code=status, headers={"Retry-After": "60"} if status == 429 else {})
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http" or scope["path"] not in self.HEAVY:
            return await self.app(scope, receive, send)
        if not self.budget.take(self.requests_per_minute, 1_000_000):
            return await self.reject(scope, receive, send, 429, "demo_rate_limit", "A demonstração atingiu o limite temporário de consultas. Tente novamente em um minuto.")
        if not self.capacity.acquire(blocking=False):
            return await self.reject(scope, receive, send, 503, "demo_busy", "A demonstração está atendendo outras consultas. Tente novamente em instantes.")
        try:
            if scope["method"] == "POST":
                chunks, size = [], 0
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    chunk = event.get("body", b"")
                    size += len(chunk)
                    if size > self.body_bytes:
                        return await self.reject(scope, receive, send, 413, "request_too_large", "A mensagem excede o limite da demonstração.")
                    chunks.append(chunk)
                    if not event.get("more_body", False):
                        break
                body = b"".join(chunks)
                consumed = False

                async def replay():
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                await self.app(scope, replay, send)
            else:
                await self.app(scope, receive, send)
        finally:
            self.capacity.release()
