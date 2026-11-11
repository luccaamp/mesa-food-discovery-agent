"""Explicit CSV contracts and transactional import into a local SQLite dataset."""

import csv
from datetime import time
import hashlib
import json
import math
import os
from .file_publish import publish_new
from pathlib import Path
import sqlite3
import tempfile

CONTRACTS = {
    "vendors": ("vendor_id", "primary_cuisine"),
    "products": ("vendor_id", "product_id", "name", "unit_price"),
    "orders": ("order_id", "customer_id", "vendor_id", "product_id", "order_day", "order_time"),
}
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE vendors (vendor_id TEXT PRIMARY KEY, primary_cuisine TEXT NOT NULL);
CREATE TABLE products (
    vendor_id TEXT NOT NULL REFERENCES vendors(vendor_id),
    product_id TEXT NOT NULL, name TEXT NOT NULL, unit_price REAL,
    PRIMARY KEY (vendor_id, product_id));
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
    order_day INTEGER NOT NULL CHECK(order_day >= 0), order_time TEXT NOT NULL);
CREATE TABLE order_items (
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    vendor_id TEXT NOT NULL, product_id TEXT NOT NULL,
    PRIMARY KEY(order_id, vendor_id, product_id),
    FOREIGN KEY(vendor_id, product_id) REFERENCES products(vendor_id, product_id));
CREATE INDEX orders_by_day ON orders(order_day, order_time, order_id);
CREATE INDEX orders_by_customer ON orders(customer_id);
"""


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_source(config_path: Path) -> tuple[dict, dict]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("tables"), dict):
        raise ValueError("Expected a JSON object with a tables mapping")
    if config.get("data_kind") not in {"synthetic", "dhrd"}:
        raise ValueError("config.data_kind must be synthetic or dhrd")
    for field in ("city", "source_url", "license"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError(f"config.{field} is required")
    sources = {}
    for table, fields in CONTRACTS.items():
        spec = config.get("tables", {}).get(table, {})
        if not isinstance(spec, dict):
            raise ValueError(f"Expected table configuration object for {table}")
        mapping = spec.get("columns", {})
        if not isinstance(mapping, dict):
            raise ValueError(f"Expected column mapping object for {table}")
        if set(mapping) != set(fields) or any(not isinstance(v, str) or not v for v in mapping.values()):
            raise ValueError(f"Explicit column mapping required for {table}: {', '.join(fields)}")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError(f"Source columns must be distinct in {table}")
        if not isinstance(spec.get("path"), str) or not spec["path"]:
            raise ValueError(f"Source path required for {table}")
        path = (config_path.parent / spec["path"]).resolve()
        if not path.is_file() or path.suffix.lower() != ".csv":
            raise ValueError(f"Expected extracted CSV for {table}")
        if not isinstance(spec.get("delimiter", ","), str) or len(spec.get("delimiter", ",")) != 1:
            raise ValueError(f"Invalid delimiter for {table}")
        sources[table] = {**spec, "path": path, "columns": mapping}
    if len({s["path"] for s in sources.values()}) != len(sources):
        raise ValueError("Each table must have a separate source file")
    return config, sources


def mapped_rows(spec: dict):
    with spec["path"].open(encoding=spec.get("encoding", "utf-8-sig"), newline="") as stream:
        reader = csv.reader(stream, delimiter=spec.get("delimiter", ","), strict=True)
        header = next(reader, [])
        if not header or len(set(header)) != len(header) or any(not h.strip() for h in header):
            raise ValueError("Missing, blank or duplicate CSV headers")
        missing = set(spec["columns"].values()) - set(header)
        if missing:
            raise ValueError(f"Missing mapped headers: {', '.join(sorted(missing))}")
        indexes = {field: header.index(source) for field, source in spec["columns"].items()}
        for record, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise ValueError(f"CSV record {record}: inconsistent number of columns")
            values = {field: row[index].strip() for field, index in indexes.items()}
            for field, value in values.items():
                if field.endswith("_id") and not value:
                    raise ValueError(f"CSV record {record}: empty identifier {field}")
            yield values


def insert_unique(connection, table: str, values: tuple, key_columns: tuple, key: tuple) -> bool:
    # Table and column names come only from internal constants, never source content.
    where = " AND ".join(f"{column} = ?" for column in key_columns)
    previous = connection.execute(f"SELECT * FROM {table} WHERE {where}", key).fetchone()
    if previous is not None:
        if previous != values:
            raise ValueError(f"Conflicting duplicate key in {table}")
        return False
    placeholders = ",".join("?" for _ in values)
    connection.execute(f"INSERT INTO {table} VALUES ({placeholders})", values)
    return True


def prepare_dataset(config_path: Path, output: Path, *, allow_test_data: bool = False) -> dict:
    """Fail on ambiguous/orphan records; never replace an existing database."""
    config, sources = read_source(config_path)
    if config["data_kind"] != "dhrd" and not allow_test_data:
        raise ValueError("Real data required. Synthetic fixtures are restricted to automated tests")
    if output.suffix.lower() != ".sqlite":
        raise ValueError("Dataset output must end in .sqlite")
    if output.exists():
        raise ValueError("Output already exists; choose a new dataset version")
    output.parent.mkdir(parents=True, exist_ok=True)
    before = {name: file_hash(spec["path"]) for name, spec in sources.items()}
    fd, temporary = tempfile.mkstemp(prefix="dataset-", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary)
    connection = sqlite3.connect(temporary)
    counts = {name: 0 for name in ("vendors", "products", "orders", "order_items")}
    duplicates = {name: 0 for name in counts}
    try:
        connection.executescript(SCHEMA)
        with connection:
            for table in CONTRACTS:
                for row in mapped_rows(sources[table]):
                    if table == "vendors":
                        values = (row["vendor_id"], row["primary_cuisine"])
                        created = insert_unique(connection, table, values, ("vendor_id",), values[:1])
                    elif table == "products":
                        price = float(row["unit_price"]) if row["unit_price"] else None
                        if price is not None and (not math.isfinite(price) or price < 0):
                            raise ValueError("unit_price must be a finite nonnegative number or blank")
                        values = (row["vendor_id"], row["product_id"], row["name"], price)
                        created = insert_unique(connection, table, values, ("vendor_id", "product_id"), values[:2])
                    else:
                        day = int(row["order_day"])
                        clock = time.fromisoformat(row["order_time"])
                        if day < 0 or clock.tzinfo is not None:
                            raise ValueError("Expected nonnegative relative day and local clock time")
                        values = (row["order_id"], row["customer_id"], day, clock.isoformat(timespec="microseconds"))
                        created_order = insert_unique(connection, "orders", values, ("order_id",), values[:1])
                        counts["orders"] += int(created_order)
                        duplicates["orders"] += int(not created_order)
                        item = (row["order_id"], row["vendor_id"], row["product_id"])
                        created = insert_unique(connection, "order_items", item,
                                                ("order_id", "vendor_id", "product_id"), item)
                        counts["order_items"] += int(created)
                        duplicates["order_items"] += int(not created)
                        continue
                    counts[table] += int(created)
                    duplicates[table] += int(not created)
            if any(value == 0 for value in counts.values()):
                raise ValueError("Each source table must contain at least one usable record")
            if before != {name: file_hash(spec["path"]) for name, spec in sources.items()}:
                raise ValueError("Source files changed during import")
            days = connection.execute("SELECT MIN(order_day), MAX(order_day) FROM orders").fetchone()
            summary = {
                "schema_version": 1, "data_kind": config["data_kind"], "city": config["city"],
                "source_url": config["source_url"], "license": config["license"],
                "source_hashes": before, "config_sha256": file_hash(config_path),
                "counts": counts, "repeated_keys": duplicates, "relative_days": list(days),
                "notes": ["Repeated order keys include normal multi-item baskets.",
                          "Repeated item lines are deduplicated; quantity is not modeled.",
                          "Composite item key is (vendor_id, product_id)."],
            }
            connection.execute("INSERT INTO metadata VALUES ('manifest', ?)", (json.dumps(summary),))
        connection.close()
        # Same-directory hard link publishes atomically without replacing an existing file.
        publish_new(temporary, output)
        return summary
    except sqlite3.IntegrityError as error:
        raise ValueError("Relational integrity failure: missing vendor/product reference or invalid record") from error
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def open_dataset(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError("Dataset does not exist; run prepare first")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        if not row or json.loads(row[0]).get("schema_version") != 1:
            raise ValueError("Unsupported dataset version")
    except Exception:
        connection.close()
        raise
    return connection
