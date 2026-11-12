import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const shots = (page: Page, name: string) =>
  page.screenshot({ path: `e2e/screenshots/${name}-${test.info().project.name}.png`, fullPage: false });

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.clear());
});

test("home shows hero, cuisines and real popular items", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "O que vamos pedir hoje?" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Culinárias" }).getByRole("link").first()).toBeVisible();
  const popular = page.getByRole("region", { name: "Mais pedidos em Singapura" });
  await expect(popular.getByRole("article").first()).toBeVisible();
  await shots(page, "home");
  await axe(page);
});

test("search translates, filters and adds to the bag", async ({ page }) => {
  await page.goto("/#/buscar?q=arroz%20com%20frango");
  await expect(page.getByRole("status").filter({ hasText: "resultados" })).toContainText("chicken");
  const first = page.getByRole("article").first();
  await first.getByRole("button", { name: /à sacola/ }).click();
  await expect(page.locator(".toast")).toContainText("na sacola");
  await expect(page.getByRole("link", { name: /Sacola, 1 itens/ })).toBeVisible();
  await shots(page, "search");
  await axe(page);
});

test("item sheet shows evidence and pairs, and returns focus on Escape", async ({ page }) => {
  await page.goto("/#/buscar?q=milk%20tea");
  const open = page.getByRole("button", { name: /Ver detalhes de/ }).first();
  await open.click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText("Preço normalizado")).toBeVisible();
  await expect(sheet.getByRole("heading", { name: "Costuma ser pedido junto" })).toBeVisible();
  await shots(page, "item");
  await axe(page);
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(open).toBeFocused();
});

test("bag suggests complements and explains the demo checkout", async ({ page }) => {
  await page.goto("/#/buscar?q=chicken%20rice");
  await page.getByRole("article").first().getByRole("button", { name: /à sacola/ }).click();
  await page.goto("/#/sacola");
  await expect(page.getByRole("heading", { name: "Sacola" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Sugestões para completar" }).getByRole("article").first()).toBeVisible();
  await shots(page, "cart");
  await axe(page);
  await page.getByRole("button", { name: "Finalizar pedido de demonstração" }).click();
  await expect(page.getByRole("heading", { name: "Este é um catálogo histórico" })).toBeVisible();
});

test("assistant streams agent steps and shows grounded items", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Pergunte à Mesa" }).click();
  const panel = page.getByRole("dialog", { name: "Assistente Mesa" });
  await panel.getByRole("textbox", { name: "Mensagem" }).fill("quero um café gelado");
  await panel.getByRole("button", { name: "Enviar" }).click();
  await expect(panel.getByRole("list", { name: "Etapas do assistente" })).toContainText(/Buscou|glossário/, { timeout: 45_000 });
  await expect(panel.getByRole("article").first()).toBeVisible({ timeout: 45_000 });
  await shots(page, "assistant");
  await axe(page);
});

test("lab presents evaluations", async ({ page }) => {
  await page.goto("/#/lab");
  await expect(page.getByRole("heading", { name: "Como sabemos que funciona" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Recomendação/ })).toBeVisible();
  const redTeam = page.getByRole("region", { name: "Tabela do red team" });
  await expect(redTeam).toContainText("LLM01");
  await expect(redTeam.getByRole("row").last()).toContainText("24/24");
  await expect(page.getByRole("link", { name: /@mesa_food_discovery_bot/ })).toHaveAttribute("href", /t\.me/);
  await shots(page, "lab");
  await axe(page);
});
