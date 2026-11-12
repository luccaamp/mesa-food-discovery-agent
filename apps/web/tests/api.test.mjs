import test from "node:test";
import assert from "node:assert/strict";
import { api, amount, priceComparison, priceLabel } from "../src/api.ts";

test("raw dataset values never become display zeros and always say they are not currency", () => {
  assert.equal(priceLabel(0.002), "0,002 (unidade do dataset, sem moeda)");
  assert.equal(priceLabel(0.0004), "0,0004 (unidade do dataset, sem moeda)");
  assert.equal(amount(0.0028000000000000004), "0,0028");
  assert.notEqual(amount(0.000000001), "0");
});

test("a recorded zero is an unknown price, never a free item", () => {
  assert.equal(priceLabel(null), "Não registrado na fonte");
  assert.equal(priceLabel(0), "Não registrado na fonte");
});

test("price bands read as a comparison within the cuisine", () => {
  const band = (level, share) => ({ level, symbol: "$".repeat(level), label: "x", pricier_share: share, reference: "pizza" });
  assert.equal(priceComparison(band(1, 0.72)), "Mais barato que 72% dos itens de pizza");
  assert.equal(priceComparison(band(3, 0.1)), "Mais caro que 90% dos itens de pizza");
  assert.equal(priceComparison({ level: null, symbol: null, label: "x", pricier_share: null, reference: "pizza" }), null);
  assert.equal(priceComparison(undefined), null);
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
