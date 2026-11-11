import test from "node:test";
import assert from "node:assert/strict";
import { api, amount, priceLabel } from "../src/api.ts";

test("normalized positive prices never become display zeros", () => {
  assert.equal(priceLabel(0.002), "0,002 u.n.");
  assert.equal(priceLabel(0.0016), "0,0016 u.n.");
  assert.equal(priceLabel(0.0004), "0,0004 u.n.");
  assert.equal(amount(0.0028000000000000004), "0,0028");
  assert.notEqual(amount(0.000000001), "0");
});

test("missing and original zero prices have distinct meaning", () => {
  assert.equal(priceLabel(null), "Não informado");
  assert.equal(priceLabel(0), "Zero na fonte");
  assert.equal(priceLabel(1), "1 u.n.");
});

test("HTML cold-start pages produce a useful retry message", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response("<html>Starting</html>", { status: 503 }),
  );
  await assert.rejects(
    api("/v1/catalog/meta"),
    /hospedagem gratuita pode estar iniciando/,
  );
});

test("rate limits and provider outages preserve understandable errors", async (t) => {
  const fake = t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(JSON.stringify({ error: { message: "quota" } }), {
        status: 429,
      }),
  );
  await assert.rejects(api("/v1/assistant"), /Aguarde um minuto/);
  fake.mock.mockImplementation(
    async () =>
      new Response(
        JSON.stringify({ error: { message: "Serviço indisponível" } }),
        { status: 503 },
      ),
  );
  await assert.rejects(api("/v1/catalog/meta"), /Serviço indisponível/);
});

test("network errors do not leak browser exceptions", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("Failed to fetch");
  });
  await assert.rejects(api("/v1/catalog/meta"), /Confira sua conexão/);
});

test("successful API responses retain the source numeric precision", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response('{"unit_price":0.002}'),
  );
  const result = await api("/v1/catalog/items/vendor/product");
  assert.equal(result.unit_price, 0.002);
});
