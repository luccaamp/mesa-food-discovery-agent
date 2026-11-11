"""Test-only fixture. Not packaged with the product or used by public commands."""

import csv
import json
from pathlib import Path

from meal_discovery.dataset import CONTRACTS


def write_synthetic_source(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tables = {
        "vendors": [("v1", "illustrative category")],
        "products": [("v1", item, f"Synthetic item {item}", "1.0") for item in ("a", "b", "c", "future")],
        "orders": [
            ("o1", "u1", "v1", "a", 0, "12:00:00"),
            ("o2", "u2", "v1", "a", 0, "13:00:00"),
            ("o2", "u2", "v1", "b", 0, "13:00:00"),
            ("o3", "u3", "v1", "c", 1, "12:00:00"),
            ("o4", "u1", "v1", "b", 2, "12:00:00"),
            ("o5", "new-user", "v1", "future", 2, "13:00:00"),
            ("o6", "u1", "v1", "c", 3, "12:00:00"),
        ],
    }
    config = {"data_kind": "synthetic", "city": "invented-test-city",
              "source_url": "synthetic://handwritten-fixture", "license": "MIT", "tables": {}}
    for name, rows in tables.items():
        path = directory / f"{name}.csv"
        with path.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(CONTRACTS[name])
            writer.writerows(rows)
        config["tables"][name] = {"path": path.name, "columns": {field: field for field in CONTRACTS[name]}}
    path = directory / "source.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
    return path
