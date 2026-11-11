"""Structural audit of official DHRD splits and comparison to the earlier SG mirror."""

import argparse
from collections import Counter
import csv
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import sqlite3
import tempfile

if __package__:
    from .verify_official_archives import ARCHIVE_HASHES, expected_members, sha256
else:
    from verify_official_archives import ARCHIVE_HASHES, expected_members, sha256

ORDER_FIELDS = ("customer_id", "geohash", "order_id", "vendor_id", "product_id", "day_of_week", "order_time", "order_day")
VENDOR_FIELDS = ("vendor_id", "chain_id", "geohash", "primary_cuisine")
PRODUCT_FIELDS = ("vendor_id", "product_id", "name", "unit_price")
MODULUS = 2 ** 256


def records(path: Path, fields):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, [])
        if len(header) != len(set(header)) or not set(fields) <= set(header):
            raise ValueError(f"Missing or ambiguous columns in {path.name}")
        indexes = [header.index(field) for field in fields]
        for number, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise ValueError(f"Inconsistent CSV width in {path.name}, record {number}")
            yield tuple(row[index].strip() for index in indexes)


class Fingerprint:
    """Order-independent row fingerprint, including multiplicity and ordered hash."""
    def __init__(self):
        self.count = self.total = self.squares = 0
        self.ordered = hashlib.sha256()

    def update(self, row):
        payload = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        digest = hashlib.sha256(payload).digest()
        value = int.from_bytes(digest, "big")
        self.count += 1
        self.total = (self.total + value) % MODULUS
        self.squares = (self.squares + value * value) % MODULUS
        self.ordered.update(payload)

    def result(self):
        return {"rows": self.count, "sha256_ordered_rows": self.ordered.hexdigest(),
                "sha256_row_sum_mod_256": f"{self.total:064x}",
                "sha256_row_squares_mod_256": f"{self.squares:064x}"}


def compare_common_fields(left: Path, right: Path, fields):
    a, b = Fingerprint(), Fingerprint()
    mismatch = Counter()
    differing_positions = 0
    sentinel = object()
    for one, two in zip_longest(records(left, fields), records(right, fields), fillvalue=sentinel):
        if one is not sentinel:
            a.update(one)
        if two is not sentinel:
            b.update(two)
        if one != two:
            differing_positions += 1
            if one is not sentinel and two is not sentinel:
                mismatch.update(field for field, x, y in zip(fields, one, two) if x != y)
    first, second = a.result(), b.result()
    multiset = all(first[key] == second[key] for key in ("rows", "sha256_row_sum_mod_256", "sha256_row_squares_mod_256"))
    return {"official_file": left.name, "earlier_file": right.name, "compared_fields": list(fields),
            "same_common_fields_and_order": differing_positions == 0,
            "same_row_multiset_fingerprint": multiset, "differing_row_positions": differing_positions,
            "differing_positions_by_field": dict(mismatch), "official": first, "earlier": second,
            "comparison": "Whitespace-trimmed common fields; export index and added latitude/longitude excluded."}


def audit_city(root: Path, city: str, workspace: Path):
    directory = root / f"data_{city}"
    with tempfile.TemporaryDirectory(prefix=f"official-{city}-", dir=workspace) as temporary:
        connection = sqlite3.connect(Path(temporary) / "audit.sqlite")
        try:
            connection.executescript("""
                CREATE TABLE vendors(vendor TEXT,chain TEXT,geo TEXT,cuisine TEXT);
                CREATE TABLE products(vendor TEXT,product TEXT,name TEXT,price TEXT);
                CREATE TABLE lines(customer TEXT,geo TEXT,oid TEXT,vendor TEXT,product TEXT,
                                   dow TEXT,clock TEXT,relative_day INTEGER,source_split TEXT);
            """)
            with connection:
                connection.executemany("INSERT INTO vendors VALUES (?,?,?,?)", records(directory / f"vendors_{city}.txt", VENDOR_FIELDS))
                connection.executemany("INSERT INTO products VALUES (?,?,?,?)", records(directory / f"products_{city}.txt", PRODUCT_FIELDS))
            fingerprints = {}
            combined = Fingerprint()
            summaries = {}
            for split, suffix in (("train", "_train"), ("test", "_test"), ("all", "")):
                path = directory / f"orders_{city}{suffix}.txt"
                current = Fingerprint()
                days = Counter()
                blanks = Counter()
                def iterator():
                    for row in records(path, ORDER_FIELDS):
                        if not re.fullmatch(r"\d+(?: days?(?: 00:00:00)?)?", row[7]):
                            raise ValueError("Unexpected relative-day format")
                        day = int(row[7].split()[0])
                        days[day] += 1
                        current.update(row)
                        blanks.update(field for field, value in zip(ORDER_FIELDS, row) if not value)
                        if split != "all":
                            combined.update(row)
                        yield (*row[:7], day, split)
                if split == "all":
                    for _ in iterator():
                        pass
                else:
                    with connection:
                        connection.executemany("INSERT INTO lines VALUES (?,?,?,?,?,?,?,?,?)", iterator())
                fingerprints[split] = current.result()
                summaries[split] = {"item_lines": current.count, "day_min": min(days), "day_max": max(days),
                                    "distinct_days": len(days), "blank_cells": dict(blanks)}
                print(f"{city}: audited {split} ({current.count:,} item lines)", flush=True)
            connection.executescript("""
                CREATE INDEX vendor_idx ON vendors(vendor);
                CREATE INDEX product_idx ON products(vendor,product);
                CREATE INDEX line_order_idx ON lines(oid,source_split);
            """)
            scalar = lambda sql, args=(): connection.execute(sql, args).fetchone()[0]
            for split in ("train", "test"):
                summaries[split].update({
                    "orders": scalar("SELECT COUNT(DISTINCT oid) FROM lines WHERE source_split=?", (split,)),
                    "customers": scalar("SELECT COUNT(DISTINCT customer) FROM lines WHERE source_split=?", (split,)),
                    "order_lines_without_product": scalar("""SELECT COUNT(*) FROM lines l WHERE source_split=?
                        AND NOT EXISTS (SELECT 1 FROM products p WHERE p.vendor=l.vendor AND p.product=l.product)""", (split,)),
                    "order_lines_without_vendor": scalar("""SELECT COUNT(*) FROM lines l WHERE source_split=?
                        AND NOT EXISTS (SELECT 1 FROM vendors v WHERE v.vendor=l.vendor)""", (split,)),
                })
            full = fingerprints["all"]
            union = combined.result()
            same_union = all(full[key] == union[key] for key in ("rows", "sha256_row_sum_mod_256", "sha256_row_squares_mod_256"))
            overlap = scalar("SELECT COUNT(*) FROM (SELECT oid FROM lines GROUP BY oid HAVING COUNT(DISTINCT source_split)>1)")
            result = {"city_code": city,
                      "catalog": {"product_rows": scalar("SELECT COUNT(*) FROM products"),
                                  "vendor_product_keys": scalar("SELECT COUNT(*) FROM (SELECT vendor,product FROM products GROUP BY vendor,product)"),
                                  "vendor_rows": scalar("SELECT COUNT(*) FROM vendors"),
                                  "vendors": scalar("SELECT COUNT(DISTINCT vendor) FROM vendors"),
                                  "cuisines": scalar("SELECT COUNT(DISTINCT cuisine) FROM vendors WHERE cuisine<>''")},
                      "splits": summaries, "row_fingerprints": fingerprints,
                      "split_checks": {"overlapping_order_ids": overlap, "train_test_multiset_matches_full": same_union,
                                       "temporal_separation": summaries["train"]["day_max"] < summaries["test"]["day_min"]},
                      "all_orders_distinct": scalar("SELECT COUNT(DISTINCT oid) FROM lines"),
                      "all_customers_distinct": scalar("SELECT COUNT(DISTINCT customer) FROM lines")}
            if overlap or not same_union or not result["split_checks"]["temporal_separation"]:
                raise ValueError(f"Official split consistency check failed for {city}")
            return result
        finally:
            connection.close()


def verify_manifest(root: Path):
    manifest = json.loads((root / "official-manifest.json").read_text(encoding="utf-8"))
    archives = manifest.get("archives", [])
    if len(archives) != len(ARCHIVE_HASHES) or {archive["city_code"] for archive in archives} != set(ARCHIVE_HASHES):
        raise ValueError("Manifest must include each official city exactly once")
    for archive in archives:
        city = archive["city_code"]
        if archive["archive_sha256"] != ARCHIVE_HASHES[city]:
            raise ValueError("Archive does not match recorded package reference")
        files = archive["files"]
        if len(files) != len(expected_members(city)) or {member["path"] for member in files} != expected_members(city):
            raise ValueError("Manifest contains unexpected or missing official file paths")
        for member in files:
            if sha256(root / member["path"]) != member["sha256"]:
                raise ValueError("Extracted official file changed")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/dhrd-official-v1"))
    parser.add_argument("--earlier-sg-dir", type=Path, default=Path("data/raw/nearbite-sg"))
    parser.add_argument("--output", type=Path, default=Path("reports/official-data-audit-v1.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new report path; existing results are protected")
    verify_manifest(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cities = [audit_city(args.input_dir, city, args.output.parent) for city in ("sg", "se", "tw")]
    official = args.input_dir / "data_sg"
    comparisons = [
        compare_common_fields(official / "products_sg.txt", args.earlier_sg_dir / "products_sg.csv", PRODUCT_FIELDS),
        compare_common_fields(official / "vendors_sg.txt", args.earlier_sg_dir / "vendors_sg_clean.csv", VENDOR_FIELDS),
        compare_common_fields(official / "orders_sg_train.txt", args.earlier_sg_dir / "orders_sg_train_clean.csv", ORDER_FIELDS),
    ]
    result = {"data_kind": "official_dhrd", "scope": "Structural audit only; no prediction or test-set metric computed.",
              "cities": cities, "singapore_mirror_comparisons": comparisons,
              "raw_products_sg_byte_identical": sha256(official / "products_sg.txt") == sha256(args.earlier_sg_dir / "products_sg.csv"),
              "archive_hashes": ARCHIVE_HASHES,
              "fingerprint_method": "Canonical JSON row SHA-256; count, modular sum and squared sum preserve multiplicities independent of row order."}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(args.output), "cities": [city["city_code"] for city in cities],
                      "sg_common_fields_identical": all(row["same_common_fields_and_order"] for row in comparisons),
                      "products_byte_identical": result["raw_products_sg_byte_identical"]}, indent=2))


if __name__ == "__main__":
    main()
