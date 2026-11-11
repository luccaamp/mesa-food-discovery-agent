import test from "node:test";
import assert from "node:assert/strict";
import { parseBlock, streamAgent } from "../src/lib/sse.ts";
import { href, parseRoute } from "../src/lib/route.ts";

test("SSE blocks parse into agent events and ignore noise", () => {
  assert.deepEqual(parseBlock('event: tool\ndata: {"type":"tool","name":"search_catalog"}'), {
    type: "tool",
    name: "search_catalog",
  });
  assert.equal(parseBlock("event: ping"), null);
  assert.equal(parseBlock("data: {broken"), null);
});

test("stream delivers events in order across chunk boundaries", async (t) => {
  const body = [
    'event: plan\ndata: {"type":"plan","provider":"groq","model":"m","tools":["search_catalog"]}\n\n',
    'event: tool\ndata: {"type":"tool","name":"search_catalog","arguments":{"query":"laksa"},"result_count":3,"duration_ms":4}\n\nevent: res',
    'ult\ndata: {"type":"result","response":{"answer":"ok","items":[],"context":{}}}\n\n',
  ];
  t.mock.method(globalThis, "fetch", async () => new Response(new ReadableStream({
    start(controller) {
      for (const chunk of body) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  }), { status: 200 }));
  const seen = [];
  const result = await streamAgent("laksa", {}, (event) => seen.push(event.type));
  assert.deepEqual(seen, ["plan", "tool", "result"]);
  assert.equal(result.answer, "ok");
});

test("stream errors become user-facing messages", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("busy", { status: 429 }));
  await assert.rejects(streamAgent("x", {}, () => {}), /limite temporário/);
});

test("hash routes round-trip", () => {
  assert.deepEqual(parseRoute("#/buscar?q=ch%C3%A1&culinaria=thai"), { page: "search", query: "chá", cuisine: "thai" });
  assert.equal(parseRoute("#/qualquer").page, "home");
  assert.equal(href("search", { q: "laksa", culinaria: "" }), "#/buscar?q=laksa");
  assert.equal(parseRoute(href("cart")).page, "cart");
});
