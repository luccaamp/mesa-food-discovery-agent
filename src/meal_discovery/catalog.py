"""Evidence-backed lexical search over a separate, historical catalog index."""

import json
import math
import os
from .file_publish import publish_new
from pathlib import Path
import re
import sqlite3
import tempfile

from .dataset import file_hash, open_dataset
from .pricing import annotate, level_clause


class CatalogUnavailable(ValueError):
    """The configured index is missing or does not meet its data contract."""


def open_catalog(index: Path, *, allow_test_data=False):
    if not index.is_file():
        raise CatalogUnavailable("Catalog index does not exist; build-catalog first")
    connection = sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key='catalog_manifest'").fetchone()
        manifest = json.loads(row[0]) if row else {}
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("index_version") != "lexical-fts5-v1":
            raise CatalogUnavailable("Unsupported catalog index")
        if manifest.get("data_kind") != "official_dhrd" and not allow_test_data:
            raise CatalogUnavailable("Search requires official real data")
        return connection, manifest
    except Exception:
        connection.close()
        raise


def catalog_metadata(index: Path, *, allow_test_data=False):
    connection, manifest = open_catalog(index, allow_test_data=allow_test_data)
    try:
        # Readiness checks structure without scanning the complete million-row catalog.
        connection.execute("SELECT vendor_id,product_id,name,unit_price,primary_cuisine FROM items LIMIT 1").fetchone()
        connection.execute("SELECT rowid FROM item_search LIMIT 1").fetchone()
        return manifest
    finally:
        connection.close()


def catalog_cuisines(index: Path, *, allow_test_data=False):
    connection, manifest = open_catalog(index, allow_test_data=allow_test_data)
    try:
        rows = connection.execute("SELECT primary_cuisine AS name,COUNT(*) AS products FROM items GROUP BY primary_cuisine ORDER BY primary_cuisine")
        return {"cuisines": [dict(row) for row in rows], "provenance": manifest}
    finally:
        connection.close()


def catalog_item(index: Path, vendor_id: str, product_id: str, *, allow_test_data=False):
    connection, manifest = open_catalog(index, allow_test_data=allow_test_data)
    try:
        row = connection.execute("SELECT vendor_id,product_id,name,unit_price,primary_cuisine FROM items WHERE vendor_id=? AND product_id=?",
                                 (vendor_id, product_id)).fetchone()
        return {"item": annotate([dict(row)])[0], "provenance": manifest} if row else None
    finally:
        connection.close()


def build_catalog(database: Path, output: Path, *, allow_test_data=False) -> dict:
    if output.exists() or output.resolve() == database.resolve():
        raise ValueError("Choose a new catalog output path")
    source = open_dataset(database)
    temporary = None
    target = None
    try:
        manifest = json.loads(source.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if manifest.get("data_kind") != "official_dhrd" and not allow_test_data:
            raise ValueError("Catalog requires verified official real data")
        before = file_hash(database)
        output.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix="catalog-", suffix=".tmp", dir=output.parent)
        os.close(handle)
        temporary = Path(name)
        target = sqlite3.connect(temporary)
        target.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE items(id INTEGER PRIMARY KEY, vendor_id TEXT NOT NULL,
                product_id TEXT NOT NULL, name TEXT NOT NULL, unit_price REAL,
                primary_cuisine TEXT NOT NULL, UNIQUE(vendor_id,product_id));
            CREATE INDEX items_cuisine_price ON items(primary_cuisine,unit_price);
            CREATE VIRTUAL TABLE item_search USING fts5(name, primary_cuisine,
                content='items', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
        """)
        with target:
            target.executemany("INSERT INTO items(vendor_id,product_id,name,unit_price,primary_cuisine) VALUES (?,?,?,?,?)",
                               source.execute("""SELECT p.vendor_id,p.product_id,p.name,p.unit_price,v.primary_cuisine
                                   FROM products p JOIN vendors v USING(vendor_id) ORDER BY p.vendor_id,p.product_id"""))
            target.execute("INSERT INTO item_search(item_search) VALUES ('rebuild')")
            summary = {"schema_version": 1, "index_version": "lexical-fts5-v1",
                       "data_kind": manifest["data_kind"], "city": manifest["city"],
                       "source_database_sha256": before, "source_hashes": manifest["source_hashes"],
                       "products": target.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                       "cuisines": target.execute("SELECT COUNT(DISTINCT primary_cuisine) FROM items").fetchone()[0],
                       "price_unit": "dataset_normalized_unit", "historical_catalog": True,
                       "limitations": ["No live availability, currency conversion or delivery-radius guarantee.",
                                       "Lexical matching only; no translation or semantic understanding.",
                                       "Catalog includes products with no observed training interactions."]}
            if file_hash(database) != before:
                raise ValueError("Source database changed during indexing")
            target.execute("INSERT INTO metadata VALUES ('catalog_manifest',?)", (json.dumps(summary),))
        target.close()
        publish_new(temporary, output)
        return summary
    finally:
        source.close()
        if target:
            target.close()
        if temporary:
            temporary.unlink(missing_ok=True)


def search_catalog(index: Path, query: str, *, cuisine=None, min_price=None, max_price=None,
                   price_level=None, limit=10, allow_test_data=False) -> dict:
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Query must contain 1 to 200 characters")
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not tokens:
        raise ValueError("Query requires letters or numbers")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50")
    for price in (min_price, max_price):
        if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0):
            raise ValueError("Price bounds must be finite nonnegative normalized values")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("Minimum price exceeds maximum price")
    if cuisine is not None and (not isinstance(cuisine, str) or not cuisine.strip() or len(cuisine) > 200):
        raise ValueError("Cuisine must be a nonempty catalog label")
    band = level_clause(price_level) if price_level is not None else None
    connection, manifest = open_catalog(index, allow_test_data=allow_test_data)
    try:
        conditions = ["item_search MATCH ?"]
        parameters = [' AND '.join('"' + token + '"' for token in tokens)]
        for value, condition in ((cuisine, "i.primary_cuisine=?"), (min_price, "i.unit_price>=?"), (max_price, "i.unit_price>0 AND i.unit_price<=?")):
            if value is not None:
                conditions.append(condition)
                parameters.append(value)
        if band:
            conditions.append(band[0])
            parameters += band[1]
        base = " FROM item_search JOIN items i ON i.id=item_search.rowid WHERE " + " AND ".join(conditions)
        total = connection.execute("SELECT COUNT(*)" + base, parameters).fetchone()[0]
        rows = connection.execute("SELECT i.vendor_id,i.product_id,i.name,i.unit_price,i.primary_cuisine,"
                                  "bm25(item_search,2.0,0.7) AS lexical_score" + base +
                                  # On equal relevance, items with a recorded price lead: 28% of the
                                  # official catalog records 0, which would otherwise win ties arbitrarily.
                                  " ORDER BY lexical_score,i.unit_price=0,i.vendor_id,i.product_id LIMIT ?",
                                  parameters + [limit])
        return {"query": query, "total_matches": total, "items": annotate([dict(row) for row in rows]),
                "filters": {"cuisine": cuisine, "min_price": min_price, "max_price": max_price, "price_level": price_level},
                "provenance": manifest, "ranking": "BM25 lexical; lower scores rank first; not a probability"}
    finally:
        connection.close()
