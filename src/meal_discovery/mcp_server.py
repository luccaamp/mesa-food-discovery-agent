"""Model Context Protocol server exposing Mesa's read-only catalog tools.

Any MCP client (Claude Desktop, Claude Code, Cursor, an IDE agent) can search
the real catalog, read an item and get basket-based recommendations through
the same domain functions the web assistant uses. Nothing is written; no SQL,
code or URLs are accepted.

Run over stdio:  mesa-mcp        (or: python -m meal_discovery.mcp_server)
"""

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .api_models import ItemRef, RecommendationParams, SearchParams
from .catalog import catalog_cuisines, catalog_item, catalog_metadata, search_catalog
from .discovery import expand_query, guarded_constraint
from .serving import recommend
from .tools import DISCLOSURE

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def catalog_path():
    return Path(os.environ.get("MEAL_CATALOG_INDEX", "data/processed/singapore-catalog-v1.sqlite"))


def serving_path():
    return Path(os.environ.get("MEAL_SERVING_INDEX", "data/processed/singapore-serving-v1.sqlite"))


def _item(row):
    return {key: row[key] for key in ("vendor_id", "product_id", "name", "unit_price", "primary_cuisine", "price_band")
            if key in row}


def build_server(*, catalog=None, serving=None, allow_test_data=False):
    catalog = Path(catalog) if catalog else catalog_path()
    serving = Path(serving) if serving else serving_path()
    options = {"allow_test_data": allow_test_data}
    server = MCPServer(
        name="mesa-food-discovery",
        title="Mesa food discovery",
        instructions=("Read-only tools over a real historical food delivery catalog from Singapore (DHRD). "
                      "Prices are normalized dataset units, not currency. Item names do not prove ingredients, "
                      "allergens or availability; never present them as guarantees. Queries work best as short "
                      "English dish or drink keywords; Portuguese dish names are expanded by a glossary."),
        version="0.9.0",
    )

    @server.tool(annotations=READ_ONLY)
    def search_catalog_items(
        query: Annotated[str, Field(min_length=1, max_length=200, description="Dish or drink, e.g. 'chicken rice'")],
        max_price: Annotated[float | None, Field(ge=0, description="Maximum normalized price")] = None,
        price_level: Annotated[int | None, Field(ge=1, le=3, description="1 = cheapest third of each cuisine, 2 = up to mid-range")] = None,
        cuisine: Annotated[str | None, Field(max_length=80, description="Exact cuisine name from list_cuisines")] = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 8,
    ) -> dict:
        """Search the historical catalog by dish or drink keywords (BM25 over item names)."""
        if guarded_constraint(query):
            return {"items": [], "notice": "The catalog cannot certify diets or allergens; search by dish name instead.",
                    "disclosure": DISCLOSURE}
        expanded, _ = expand_query(query)
        params = SearchParams(query=expanded or query, cuisine=cuisine, max_price=max_price,
                              price_level=price_level, limit=limit)
        result = search_catalog(catalog, **params.model_dump(), **options)
        return {"query": params.query, "total_matches": result["total_matches"],
                "items": [_item(row) for row in result["items"]], "disclosure": DISCLOSURE}

    @server.tool(annotations=READ_ONLY)
    def get_item(
        vendor_id: Annotated[str, Field(min_length=1, max_length=200)],
        product_id: Annotated[str, Field(min_length=1, max_length=200)],
    ) -> dict:
        """Read one catalog item by its anonymized vendor and product identifiers."""
        found = catalog_item(catalog, vendor_id, product_id, **options)
        if found is None:
            return {"found": False}
        return {"found": True, "item": _item(found["item"]), "disclosure": DISCLOSURE}

    @server.tool(annotations=READ_ONLY)
    def recommend_items(
        seeds: Annotated[list[ItemRef] | None, Field(max_length=5, description="Up to five items the user liked")] = None,
        max_price: Annotated[float | None, Field(ge=0)] = None,
        price_level: Annotated[int | None, Field(ge=1, le=3)] = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 6,
    ) -> dict:
        """Items frequently bought together with the seeds in real baskets, completed by popularity."""
        params = RecommendationParams(seeds=seeds or [], max_price=max_price, price_level=price_level, limit=limit)
        result = recommend(serving, [(seed.vendor_id, seed.product_id) for seed in params.seeds],
                           max_price=params.max_price, price_level=params.price_level, limit=params.limit, **options)
        return {"items": [{**_item(row), "reason": row.get("reason"), "training_baskets": row.get("training_baskets")}
                          for row in result["items"]], "disclosure": DISCLOSURE}

    @server.tool(annotations=READ_ONLY)
    def list_cuisines() -> dict:
        """Cuisine names available as filters, with product counts."""
        return catalog_cuisines(catalog, **options)

    @server.resource("mesa://catalog/provenance", mime_type="application/json")
    def provenance() -> dict:
        """Source dataset, hashes and limits of the served catalog."""
        return catalog_metadata(catalog, **options)

    return server


def main():
    build_server().run("stdio")


if __name__ == "__main__":
    main()
