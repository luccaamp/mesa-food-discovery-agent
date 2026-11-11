"""Versioned adapters for official Singapore training data and historical mirror."""

import csv
from datetime import time
import json
import math
import os
from .file_publish import publish_new
from pathlib import Path
import re
import sqlite3
import tempfile

from .dataset import SCHEMA, file_hash

SOURCE_URL = "https://github.com/jpchawanda1/nearbite-recommender/blob/a58e7255e22fbf7ed60f4854c041a41ba5a5c454/scripts/download_data.py"
SOURCE_HASHES = {
    "vendors_sg_clean.csv": "a0c4987daa7bd9f84b57ac04169fc04f7e9004d579884aa9c0a412a37d6c0f80",
    "products_sg.csv": "63e981a45619a3a7e62af8a037ffb641e7410fee35e26b4882f9db6de5e1385c",
    "orders_sg_train_clean.csv": "4d3ceb436c2f66872663357df223fb45b7cff9753c60ca70cd180f62d7acf1c6",
}
OFFICIAL_ARCHIVE_HASH = "55a94a5c7eeba9610776b864aae7d653426afdb8aae93e5fa5050cbdc1c25d32"
OFFICIAL_HASHES = {
    "vendors_sg.txt": "34d92d1c423db48156c59de74fa5cd3246c94d80eec3e7e759c5f46ae32da641",
    "products_sg.txt": "63e981a45619a3a7e62af8a037ffb641e7410fee35e26b4882f9db6de5e1385c",
    "orders_sg_train.txt": "4e4cbfbdf9731531ef0dde02538e62096b523b73a00a5c20bc3e5d6d6c7244e0",
}
OFFICIAL_TEST_HASH = "3903a8b261ae6499c85d10341b1c94def746a6f8059c2a534c6c3700b2257118"


def rows(path: Path, fields):
    """Ignore only the known export index; require unambiguous named columns."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, [])
        if len(set(header)) != len(header) or any(field not in header for field in fields):
            raise ValueError(f"Missing or duplicate mapped headers in {path.name}")
        extra = set(header) - set(fields)
        allowed = {"", "Unnamed: 0", "latitude", "longitude"}
        if extra - allowed:
            raise ValueError(f"Unexpected unhandled source columns in {path.name}")
        indexes = [header.index(field) for field in fields]
        for record, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise ValueError(f"Malformed record {record} in {path.name}")
            result = tuple(row[index].strip() for index in indexes)
            for field, value in zip(fields, result):
                if field.endswith("_id") and field != "chain_id" and not value:
                    raise ValueError(f"Empty identifier in {path.name}")
            yield result


def parse_day(value: str) -> int:
    if not re.fullmatch(r"\d+(?: days?(?: 00:00:00)?)?", value):
        raise ValueError("Expected nonnegative integer day or exact whole-day timedelta")
    return int(value.split()[0])


def prepare_singapore(directory: Path, output: Path, *, allow_test_data=False, progress=None) -> dict:
    """Quarantine whole orphan-containing orders; raw files stay immutable."""
    manifest = json.loads((directory / "download-manifest.json").read_text(encoding="utf-8"))
    expected_kind = "synthetic" if allow_test_data else "real_third_party_copy"
    if manifest.get("data_kind") != expected_kind:
        raise ValueError("Real Singapore mirror data required")
    hashes = {name: file_hash(directory / name) for name in SOURCE_HASHES}
    declared = {entry["file"]: entry["sha256"] for entry in manifest["files"]}
    if hashes != {name: declared.get(name) for name in hashes}:
        raise ValueError("Source hashes differ from download manifest")
    if not allow_test_data and hashes != SOURCE_HASHES:
        raise ValueError("Source does not match the audited Singapore mirror version")
    return _prepare_verified(
        {"vendors": directory / "vendors_sg_clean.csv", "products": directory / "products_sg.csv",
         "orders": directory / "orders_sg_train_clean.csv"}, output,
        hashes=hashes, kind=expected_kind, adapter="singapore-v1", source_url=SOURCE_URL,
        license_note="DHRD MIT according to source; third-party cleaned mirror", progress=progress)


def prepare_official_singapore(root: Path, output: Path, *, allow_test_data=False, progress=None) -> dict:
    """Read only the three official training/catalog files, never the test rows."""
    manifest = json.loads((root / "official-manifest.json").read_text(encoding="utf-8"))
    kind = "synthetic" if allow_test_data else "official_dhrd"
    if manifest.get("data_kind") != kind:
        raise ValueError("Verified official DHRD sources required")
    matches = [entry for entry in manifest["archives"] if entry["city_code"] == "sg"]
    if len(matches) != 1:
        raise ValueError("Expected one official Singapore archive manifest")
    archive = matches[0]
    if not allow_test_data and archive["archive_sha256"] != OFFICIAL_ARCHIVE_HASH:
        raise ValueError("Unknown official Singapore archive version")
    declared = {Path(entry["path"]).name: entry["sha256"] for entry in archive["files"]}
    files = {"vendors": root / "data_sg/vendors_sg.txt", "products": root / "data_sg/products_sg.txt",
             "orders": root / "data_sg/orders_sg_train.txt"}
    hashes = {path.name: file_hash(path) for path in files.values()}
    if hashes != {name: declared.get(name) for name in hashes}:
        raise ValueError("Official source differs from the extracted manifest")
    if not allow_test_data and (hashes != OFFICIAL_HASHES or declared.get("orders_sg_test.txt") != OFFICIAL_TEST_HASH):
        raise ValueError("Official source version does not match pinned hashes")
    reference = {"path": "data_sg/orders_sg_test.txt", "sha256": declared.get("orders_sg_test.txt"),
                 "relative_days": [76, 90], "loaded_into_training_database": False, "evaluated": False}
    return _prepare_verified(files, output, hashes=hashes, kind=kind, adapter="singapore-official-v1",
                             source_url="https://github.com/deliveryhero/dh-reco-dataset",
                             license_note="DHRD MIT according to publisher README", progress=progress,
                             reserved_test=reference)


def _prepare_verified(files, output, *, hashes, kind, adapter, source_url, license_note,
                      progress=None, reserved_test=None):
    emit = progress or (lambda message: None)
    if output.suffix != ".sqlite" or output.exists():
        raise ValueError("Choose a new .sqlite dataset path")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="singapore-", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    connection = sqlite3.connect(temporary)
    connection.execute("PRAGMA cache_size=-131072")
    try:
        connection.executescript(SCHEMA + """
            CREATE TABLE vendor_context (
                vendor_id TEXT PRIMARY KEY REFERENCES vendors(vendor_id), chain_id TEXT, geohash TEXT NOT NULL);
            CREATE TABLE order_context (
                order_id TEXT PRIMARY KEY REFERENCES orders(order_id), geohash TEXT NOT NULL,
                day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6));
            CREATE TABLE quarantined_orders (order_id TEXT PRIMARY KEY, reason TEXT NOT NULL);
            CREATE TABLE _lines (order_id TEXT, customer_id TEXT, vendor_id TEXT, product_id TEXT,
                                 order_day INTEGER, order_time TEXT, geohash TEXT, day_of_week INTEGER);
        """)
        def products():
            fields = ("vendor_id", "product_id", "name", "unit_price")
            for vendor, product, item_name, price in rows(files["products"], fields):
                number = float(price) if price else None
                if number is not None and (not math.isfinite(number) or number < 0):
                    raise ValueError("Invalid normalized price")
                yield vendor, product, item_name, number
        def orders():
            fields = ("order_id", "customer_id", "vendor_id", "product_id", "order_day", "order_time", "geohash", "day_of_week")
            for number, row in enumerate(rows(files["orders"], fields), 1):
                clock = time.fromisoformat(row[5])
                dow = int(row[7])
                if clock.tzinfo is not None or not 0 <= dow <= 6:
                    raise ValueError("Invalid clock time or day of week")
                if number % 500_000 == 0:
                    emit(f"Read {number:,} source item lines")
                yield (*row[:4], parse_day(row[4]), clock.isoformat(timespec="microseconds"), row[6], dow)
        with connection:
            emit("Loading vendor metadata")
            for vendor, cuisine, chain, geohash in rows(files["vendors"], ("vendor_id", "primary_cuisine", "chain_id", "geohash")):
                connection.execute("INSERT INTO vendors VALUES (?,?)", (vendor, cuisine))
                connection.execute("INSERT INTO vendor_context VALUES (?,?,?)", (vendor, chain or None, geohash))
            emit("Loading product catalog")
            connection.executemany("INSERT INTO products VALUES (?,?,?,?)", products())
            emit("Loading source order lines")
            connection.executemany("INSERT INTO _lines VALUES (?,?,?,?,?,?,?,?)", orders())
            connection.execute("CREATE INDEX _line_orders ON _lines(order_id)")
            conflict = connection.execute("""SELECT 1 FROM _lines GROUP BY order_id
                HAVING MIN(customer_id) <> MAX(customer_id) OR MIN(order_day) <> MAX(order_day)
                    OR MIN(order_time) <> MAX(order_time) OR MIN(geohash) <> MAX(geohash)
                    OR MIN(day_of_week) <> MAX(day_of_week) LIMIT 1""").fetchone()
            if conflict:
                raise ValueError("Conflicting customer/time/location metadata within an order")
            if connection.execute("SELECT 1 FROM _lines l WHERE NOT EXISTS (SELECT 1 FROM vendors v WHERE v.vendor_id=l.vendor_id) LIMIT 1").fetchone():
                raise ValueError("An order references an unknown vendor")
            orphan_lines = connection.execute("""SELECT COUNT(*) FROM _lines l WHERE NOT EXISTS
                (SELECT 1 FROM products p WHERE p.vendor_id=l.vendor_id AND p.product_id=l.product_id)""").fetchone()[0]
            connection.execute("""INSERT INTO quarantined_orders
                SELECT DISTINCT l.order_id, 'missing_catalog_product' FROM _lines l WHERE NOT EXISTS
                (SELECT 1 FROM products p WHERE p.vendor_id=l.vendor_id AND p.product_id=l.product_id)""")
            excluded_orders = connection.execute("SELECT COUNT(*) FROM quarantined_orders").fetchone()[0]
            excluded_lines = connection.execute("SELECT COUNT(*) FROM _lines WHERE order_id IN (SELECT order_id FROM quarantined_orders)").fetchone()[0]
            source_lines = connection.execute("SELECT COUNT(*) FROM _lines").fetchone()[0]
            source_orders = connection.execute("SELECT COUNT(DISTINCT order_id) FROM _lines").fetchone()[0]
            emit(f"Quarantining {excluded_orders:,} whole orders ({excluded_lines:,} item lines)")
            connection.execute("""INSERT INTO orders SELECT order_id, MIN(customer_id), MIN(order_day), MIN(order_time)
                FROM _lines WHERE order_id NOT IN (SELECT order_id FROM quarantined_orders) GROUP BY order_id""")
            connection.execute("""INSERT INTO order_context SELECT order_id, MIN(geohash), MIN(day_of_week)
                FROM _lines WHERE order_id NOT IN (SELECT order_id FROM quarantined_orders) GROUP BY order_id""")
            connection.execute("""INSERT INTO order_items SELECT DISTINCT order_id,vendor_id,product_id FROM _lines
                WHERE order_id NOT IN (SELECT order_id FROM quarantined_orders)""")
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("vendors", "products", "orders", "order_items")}
            if any(count == 0 for count in counts.values()):
                raise ValueError("Prepared dataset has an empty required table")
            day_counts = [dict(zip(("day", "orders", "item_lines"), record)) for record in connection.execute("""
                SELECT o.order_day, COUNT(DISTINCT o.order_id), COUNT(*) FROM orders o JOIN order_items i USING(order_id)
                GROUP BY o.order_day ORDER BY o.order_day""")]
            summary = {"schema_version": 1, "adapter_version": adapter, "city": "Singapore",
                       "data_kind": kind, "source_url": source_url,
                       "license": license_note,
                       "source_hashes": hashes, "counts": counts,
                       "relative_days": [day_counts[0]["day"], day_counts[-1]["day"]], "day_counts": day_counts,
                       "source_counts": {"orders": source_orders, "item_lines": source_lines},
                       "quarantine": {"policy": "exclude_whole_order", "orphan_item_lines": orphan_lines,
                                      "excluded_orders": excluded_orders, "excluded_item_lines": excluded_lines},
                       "deduplicated_item_lines": source_lines - excluded_lines - counts["order_items"],
                       "notes": ["Raw files are unchanged and pinned by SHA-256.",
                                 "No price/cuisine/location values were fabricated.",
                                 "Export index and any mirror-added latitude/longitude were explicitly ignored.",
                                 "Geohashes are retained as supplied, not interpreted as exact locations."]}
            if reserved_test:
                summary["official_test_reference"] = reserved_test
                if summary["relative_days"][1] > 75:
                    raise ValueError("Official test days cannot enter the training database")
            if hashes != {path.name: file_hash(path) for path in files.values()}:
                raise ValueError("Sources changed during preparation")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Foreign key integrity check failed")
            connection.execute("INSERT INTO metadata VALUES ('manifest', ?)", (json.dumps(summary),))
            connection.execute("DROP TABLE _lines")
        connection.close()
        publish_new(temporary, output)
        return summary
    except sqlite3.IntegrityError as error:
        raise ValueError("Invalid or duplicate source records; dataset was not published") from error
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)
