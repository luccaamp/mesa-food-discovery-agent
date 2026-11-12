"""MCP server contract through a real in-memory MCP client session."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

try:
    from mcp import Client
except ImportError as error:  # pragma: no cover - optional extra
    raise unittest.SkipTest("Install .[mcp] to run MCP tests") from error

from meal_discovery.catalog import build_catalog
from meal_discovery.mcp_server import build_server
from meal_discovery.serving import build_serving
from meal_discovery.singapore import prepare_singapore
from test_singapore import source_fixture


def payload(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


class McpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        source_fixture(root / "raw")
        dataset = root / "dataset.sqlite"
        prepare_singapore(root / "raw", dataset, allow_test_data=True)
        cls.catalog, cls.serving = root / "catalog.sqlite", root / "serving.sqlite"
        build_catalog(dataset, cls.catalog, allow_test_data=True)
        build_serving(dataset, cls.serving, allow_test_data=True)
        cls.server = build_server(catalog=cls.catalog, serving=cls.serving, allow_test_data=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def session(self, steps):
        async def go():
            async with Client(self.server, raise_exceptions=True) as client:
                return await steps(client)
        return asyncio.run(go())

    def test_lists_only_read_only_tools(self):
        async def steps(client):
            return (await client.list_tools()).tools
        tools = {tool.name: tool for tool in self.session(steps)}
        self.assertEqual(set(tools), {"search_catalog_items", "get_item", "recommend_items", "list_cuisines"})
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)

    def test_search_get_and_recommend_return_catalog_rows(self):
        async def steps(client):
            found = payload(await client.call_tool("search_catalog_items", {"query": "test", "limit": 5}))
            first = found["items"][0]
            item = payload(await client.call_tool("get_item", {"vendor_id": first["vendor_id"], "product_id": first["product_id"]}))
            recs = payload(await client.call_tool("recommend_items", {"seeds": [
                {"vendor_id": first["vendor_id"], "product_id": first["product_id"]}]}))
            missing = payload(await client.call_tool("get_item", {"vendor_id": "nope", "product_id": "nope"}))
            return found, item, recs, missing
        found, item, recs, missing = self.session(steps)
        self.assertGreater(found["total_matches"], 0)
        self.assertIn("faixas", found["disclosure"])
        self.assertEqual(item["item"]["name"], found["items"][0]["name"])
        self.assertTrue(all(row["reason"] in {"basket_association", "historical_popularity"} for row in recs["items"]))
        self.assertEqual(missing, {"found": False})

    def test_dietary_guarantees_are_refused_and_invalid_arguments_rejected(self):
        async def steps(client):
            guarded = payload(await client.call_tool("search_catalog_items", {"query": "gluten free bread"}))
            invalid = await client.call_tool("search_catalog_items", {"query": "x", "limit": 500})
            return guarded, invalid.is_error
        guarded, rejected = self.session(steps)
        self.assertEqual(guarded["items"], [])
        self.assertIn("cannot certify", guarded["notice"])
        self.assertTrue(rejected)


if __name__ == "__main__":
    unittest.main()
