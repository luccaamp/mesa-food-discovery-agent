"""Versioned read-only recommendation artifacts fitted only through day 61."""

import json
import math
import os
from .file_publish import publish_new
from pathlib import Path
import sqlite3
import tempfile

from .benchmark import baskets
from .catalog import CatalogUnavailable
from .dataset import file_hash, open_dataset
from .recommendation import Recommender


def build_serving(database, output, *, allow_test_data=False, progress=None):
    if output.exists() or output.suffix != ".sqlite":
        raise ValueError("Choose a new serving SQLite path")
    source = open_dataset(database)
    target = None
    temporary = None
    try:
        manifest = json.loads(source.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if manifest.get("data_kind") != "official_dhrd" and not allow_test_data:
            raise ValueError("Serving requires official real data")
        source_hash = file_hash(database)
        model = Recommender(baskets(source, -1, 61), include_user_similarity=False,
                            include_basket_similarity=True, progress=progress)
        output.parent.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix="serving-", suffix=".tmp", dir=output.parent)
        os.close(handle)
        temporary = Path(filename)
        target = sqlite3.connect(temporary)
        target.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE items(vendor_id TEXT,product_id TEXT,name TEXT,unit_price REAL,primary_cuisine TEXT,
                PRIMARY KEY(vendor_id,product_id));
            CREATE TABLE popularity(vendor_id TEXT,product_id TEXT,baskets INTEGER,
                PRIMARY KEY(vendor_id,product_id));
            CREATE INDEX popular_first ON popularity(baskets DESC,vendor_id,product_id);
            CREATE TABLE neighbors(seed_vendor TEXT,seed_product TEXT,vendor_id TEXT,product_id TEXT,
                similarity REAL,co_baskets INTEGER,PRIMARY KEY(seed_vendor,seed_product,vendor_id,product_id));
        """)
        with target:
            target.executemany("INSERT INTO items VALUES (?,?,?,?,?)", source.execute("""SELECT p.vendor_id,p.product_id,
                p.name,p.unit_price,v.primary_cuisine FROM products p JOIN vendors v USING(vendor_id)"""))
            target.executemany("INSERT INTO popularity VALUES (?,?,?)", [(key[0], key[1], count) for key, count in model.popularity.items()])
            def neighbors():
                for seed in sorted(model.basket_pairs):
                    for item, score in model._compute_basket_neighbors(seed):
                        yield seed[0], seed[1], item[0], item[1], score, model.basket_pairs[seed][item]
            target.executemany("INSERT INTO neighbors VALUES (?,?,?,?,?,?)", neighbors())
            result = {"schema_version": 1, "artifact_version": "basket-serving-v1", "data_kind": manifest["data_kind"],
                      "city": manifest["city"], "source_database_sha256": source_hash,
                      "source_hashes": manifest["source_hashes"], "train_end_day_inclusive": 61,
                      "training_orders": model.training_orders, "training_items": len(model.catalog),
                      "neighbor_edges": target.execute("SELECT COUNT(*) FROM neighbors").fetchone()[0],
                      "shrinkage": model.shrinkage, "neighbors_per_seed": model.neighbor_limit,
                      "historical_catalog": True, "price_unit": "dataset_normalized_unit",
                      "official_test_evaluated": False,
                      "limitations": "Explicit selected items seed co-basket retrieval; no fabricated user history, live availability or dietary guarantees. This interaction is not the historical next-basket benchmark protocol."}
            if file_hash(database) != source_hash:
                raise ValueError("Source changed while fitting serving artifact")
            target.execute("INSERT INTO metadata VALUES ('serving_manifest',?)", (json.dumps(result),))
        target.close()
        publish_new(temporary, output)
        return result
    finally:
        source.close()
        if target:
            target.close()
        if temporary:
            temporary.unlink(missing_ok=True)


def recommend(index: Path, seeds, *, cuisine=None, min_price=None, max_price=None, limit=10, allow_test_data=False):
    if not index.is_file():
        raise CatalogUnavailable("Recommendation artifact is unavailable")
    if type(limit) is not int or not 1 <= limit <= 20 or len(seeds) > 5 or len(seeds) != len(set(seeds)):
        raise ValueError("Use up to five distinct seed items and a result limit of 1–20")
    for value in (min_price, max_price):
        if value is not None and (type(value) not in {float, int} or not math.isfinite(value) or value < 0):
            raise ValueError("Price bounds must be finite nonnegative normalized values")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("Minimum price exceeds maximum price")
    connection = sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key='serving_manifest'").fetchone()
        manifest = json.loads(row[0]) if row else {}
        if manifest.get("artifact_version") != "basket-serving-v1" or manifest.get("train_end_day_inclusive") != 61:
            raise CatalogUnavailable("Unsupported recommendation artifact")
        if manifest.get("data_kind") != "official_dhrd" and not allow_test_data:
            raise CatalogUnavailable("Recommendations require official real data")
        for vendor, product in seeds:
            if not connection.execute("SELECT 1 FROM items WHERE vendor_id=? AND product_id=?", (vendor, product)).fetchone():
                raise ValueError("Selected seed item is absent from the real catalog")
        conditions = []
        params = []
        for value, clause in ((cuisine, "i.primary_cuisine=?"), (min_price, "i.unit_price>=?"), (max_price, "i.unit_price<=?")):
            if value is not None:
                conditions.append(clause)
                params.append(value)
        filters = " AND " + " AND ".join(conditions) if conditions else ""
        items = []
        if seeds:
            seed_clause = " OR ".join("(n.seed_vendor=? AND n.seed_product=?)" for _ in seeds)
            query = """SELECT i.*,SUM(n.similarity) AS score,SUM(n.co_baskets) AS supporting_co_baskets,
                p.baskets AS training_baskets FROM neighbors n JOIN items i USING(vendor_id,product_id)
                JOIN popularity p USING(vendor_id,product_id) WHERE (""" + seed_clause + ")" + filters + """
                GROUP BY i.vendor_id,i.product_id ORDER BY score DESC,p.baskets DESC,i.vendor_id,i.product_id LIMIT ?"""
            items = [dict(row) for row in connection.execute(query, [part for seed in seeds for part in seed] + params + [limit + len(seeds)])
                     if (row["vendor_id"], row["product_id"]) not in seeds][:limit]
            for item in items:
                item["reason"] = "basket_association"
        selected = {(row["vendor_id"], row["product_id"]) for row in items} | set(seeds)
        # CROSS JOIN keeps popularity as the outer loop, and ordering by its own columns lets SQLite walk the
        # popular_first index in order and stop at LIMIT instead of sorting the whole catalog (~1 s -> ~40 ms).
        fallback = connection.execute("""SELECT i.*,p.baskets AS training_baskets FROM popularity p
            CROSS JOIN items i ON i.vendor_id=p.vendor_id AND i.product_id=p.product_id WHERE 1=1""" + filters +
            " ORDER BY p.baskets DESC,p.vendor_id,p.product_id LIMIT ?", params + [limit + len(selected)])
        for row in fallback:
            if len(items) >= limit:
                break
            key = (row["vendor_id"], row["product_id"])
            if key not in selected:
                items.append({**dict(row), "score": None, "supporting_co_baskets": 0, "reason": "historical_popularity"})
                selected.add(key)
        return {"items": items, "seeds": [{"vendor_id": seed[0], "product_id": seed[1]} for seed in seeds],
                "filters": {"cuisine": cuisine, "min_price": min_price, "max_price": max_price}, "provenance": manifest}
    finally:
        connection.close()
