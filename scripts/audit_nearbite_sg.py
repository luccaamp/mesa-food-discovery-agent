"""Audit downloaded real Singapore tables without exporting individual records."""

import argparse
from collections import Counter
import csv
from datetime import time
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile

if __package__:
    from .fetch_nearbite_sg import FILES, inspect_file
else:
    from fetch_nearbite_sg import FILES, inspect_file


def source_rows(path, fields):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader)
        indexes = [header.index(field) for field in fields]
        for line, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise ValueError(f"Malformed CSV record {line} in {path.name}")
            yield tuple(row[index].strip() for index in indexes)


def audit(directory: Path, workspace: Path) -> dict:
    manifest = json.loads((directory / "download-manifest.json").read_text(encoding="utf-8"))
    verified = {record["file"]: record for record in manifest["files"]}
    for name, expected in FILES.items():
        if inspect_file(directory / name, expected)["sha256"] != verified[name]["sha256"]:
            raise ValueError(f"Source changed after download: {name}")
    with tempfile.TemporaryDirectory(prefix="sg-audit-", dir=workspace) as folder:
        connection = sqlite3.connect(Path(folder) / "audit.sqlite")
        try:
            connection.executescript("""
                CREATE TABLE vendors (vendor TEXT, cuisine TEXT);
                CREATE TABLE products (vendor TEXT, product TEXT, name TEXT, price TEXT);
                CREATE TABLE orders (order_id TEXT, customer TEXT, vendor TEXT, product TEXT,
                                     day INTEGER, clock TEXT, geohash TEXT, dow TEXT);
            """)
            blanks = Counter()
            days = Counter()
            invalid_prices = 0
            invalid_times = 0
            negative_prices = 0
            def products():
                nonlocal invalid_prices, negative_prices
                for row in source_rows(directory / "products_sg.csv", ("vendor_id", "product_id", "name", "unit_price")):
                    for field, value in zip(("product.vendor_id", "product.product_id", "product.name", "product.price"), row):
                        blanks[field] += int(not value)
                    if row[3]:
                        try:
                            number = float(row[3])
                            invalid_prices += int(not math.isfinite(number))
                            negative_prices += int(number < 0)
                        except ValueError:
                            invalid_prices += 1
                    yield row
            def orders():
                nonlocal invalid_times
                fields = ("order_id", "customer_id", "vendor_id", "product_id", "order_day", "order_time", "geohash", "day_of_week")
                for row in source_rows(directory / "orders_sg_train_clean.csv", fields):
                    for field, value in zip(fields, row):
                        blanks["order." + field] += int(not value)
                    if not re.fullmatch(r"-?\d+(?: days?(?: 00:00:00)?)?", row[4]):
                        raise ValueError("Unrecognized relative-day representation")
                    day = int(row[4].split()[0])
                    days[day] += 1
                    try:
                        parsed = time.fromisoformat(row[5])
                        invalid_times += int(parsed.tzinfo is not None)
                    except ValueError:
                        invalid_times += 1
                    yield (*row[:4], day, *row[5:])
            with connection:
                connection.executemany("INSERT INTO vendors VALUES (?,?)", source_rows(directory / "vendors_sg_clean.csv", ("vendor_id", "primary_cuisine")))
                connection.executemany("INSERT INTO products VALUES (?,?,?,?)", products())
                print("Catalog loaded for relational checks", flush=True)
                connection.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", orders())
            print("Orders loaded for relational checks", flush=True)
            connection.executescript("""
                CREATE INDEX vendor_idx ON vendors(vendor);
                CREATE INDEX product_idx ON products(vendor, product);
                CREATE INDEX order_idx ON orders(order_id);
            """)
            scalar = lambda sql: connection.execute(sql).fetchone()[0]
            counts = {
                "vendor_rows": scalar("SELECT COUNT(*) FROM vendors"),
                "vendors": scalar("SELECT COUNT(DISTINCT vendor) FROM vendors"),
                "cuisines": scalar("SELECT COUNT(DISTINCT cuisine) FROM vendors WHERE cuisine <> ''"),
                "product_rows": scalar("SELECT COUNT(*) FROM products"),
                "distinct_products": scalar("SELECT COUNT(*) FROM (SELECT vendor,product FROM products GROUP BY vendor,product)"),
                "order_item_rows": scalar("SELECT COUNT(*) FROM orders"),
                "orders": scalar("SELECT COUNT(DISTINCT order_id) FROM orders"),
                "customers": scalar("SELECT COUNT(DISTINCT customer) FROM orders"),
                "vendors_in_orders": scalar("SELECT COUNT(DISTINCT vendor) FROM orders"),
                "unique_product_pairs_in_orders": scalar("SELECT COUNT(*) FROM (SELECT vendor,product FROM orders GROUP BY vendor,product)"),
            }
            integrity = {
                "duplicate_vendor_keys": counts["vendor_rows"] - counts["vendors"],
                "duplicate_product_keys": counts["product_rows"] - counts["distinct_products"],
                "conflicting_product_metadata_keys": scalar("SELECT COUNT(*) FROM (SELECT vendor,product FROM products GROUP BY vendor,product HAVING COUNT(DISTINCT name)>1 OR COUNT(DISTINCT price)>1)"),
                "product_rows_without_vendor": scalar("SELECT COUNT(*) FROM products p WHERE NOT EXISTS (SELECT 1 FROM vendors v WHERE v.vendor=p.vendor)"),
                "order_rows_without_vendor": scalar("SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM vendors v WHERE v.vendor=o.vendor)"),
                "order_rows_without_catalog_product": scalar("SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.vendor=o.vendor AND p.product=o.product)"),
                "orders_with_conflicting_customer_day_or_time": scalar("SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(DISTINCT customer)>1 OR COUNT(DISTINCT day)>1 OR COUNT(DISTINCT clock)>1)"),
                "invalid_price_values": invalid_prices, "negative_price_values": negative_prices,
                "invalid_clock_values": invalid_times,
            }
            return {"data_kind": "real_third_party_copy", "city": "Singapore", "counts": counts,
                    "integrity": integrity, "blank_cells": dict(blanks),
                    "relative_days": {"min": min(days), "max": max(days), "distinct": len(days)},
                    "source_hashes": {name: record["sha256"] for name, record in verified.items()},
                    "limitations": manifest["limitations"],
                    "note": "Counts describe this mirror. Rows are item lines, not independent orders."}
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/nearbite-sg"))
    parser.add_argument("--output", type=Path, default=Path("reports/nearbite-sg-audit.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new audit report path; existing reports are not replaced")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = audit(args.input_dir, args.output.parent)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
