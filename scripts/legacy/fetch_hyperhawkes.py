"""Fetch a pinned, public, real DHRD derivative; never substitute synthetic data."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from meal_discovery.file_publish import publish_new
from pathlib import Path
import urllib.request

REVISION = "df2b334bf6444e0da03a1879a2cb8132fa6e71fa"
SOURCE_PATH = "dataset/dhrd/dhrd.inter"
URL = f"https://raw.githubusercontent.com/dbis-uibk/HyperHawkes/{REVISION}/{SOURCE_PATH}"
EXPECTED_BYTES = 49_974_096
EXPECTED_GIT_BLOB = "1f7c89bf9f3ba91bd6fe526ea44467ac7f45db02"


def verified_hashes(path):
    blob = hashlib.sha1(usedforsecurity=False)
    blob.update(f"blob {EXPECTED_BYTES}\0".encode())
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            blob.update(chunk)
            sha256.update(chunk)
    if size != EXPECTED_BYTES or blob.hexdigest() != EXPECTED_GIT_BLOB:
        raise ValueError("Downloaded data does not match the pinned public Git object")
    return sha256.hexdigest()


def profile(path):
    users, items = Counter(), Counter()
    products, sessions = {}, {}
    name_conflicts, vendor_conflicts = set(), set()
    session_conflicts = 0
    minimum_time, maximum_time = math.inf, -math.inf
    rows = 0
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        header = reader.fieldnames
        if not header or len(set(header)) != len(header):
            raise ValueError("Invalid derivative header")
        columns = {field.split(":")[0]: field for field in header}
        if not {"user_id", "item_id", "timestamp"} <= set(columns):
            raise ValueError("Expected user/item/time columns not found")
        missing = Counter()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed TSV record")
            rows += 1
            for field, value in row.items():
                missing[field] += int(not value.strip())
            users[row[columns["user_id"]]] += 1
            items[row[columns["item_id"]]] += 1
            stamp = float(row[columns["timestamp"]])
            if not math.isfinite(stamp):
                raise ValueError("Non-finite timestamp")
            minimum_time, maximum_time = min(minimum_time, stamp), max(maximum_time, stamp)
            if {"vendor_id", "item_name", "session_id"} <= set(columns):
                item = row[columns["item_id"]]
                metadata = (row[columns["vendor_id"]], row[columns["item_name"]])
                previous = products.setdefault(item, metadata)
                if previous[0] != metadata[0]:
                    vendor_conflicts.add(item)
                if previous[1] != metadata[1]:
                    name_conflicts.add(item)
                session = row[columns["session_id"]]
                user = row[columns["user_id"]]
                session_conflicts += int(sessions.setdefault(session, user) != user)
    return {"columns": header, "interactions": rows, "users": len(users), "items": len(items),
            "minimum_interactions_per_user": min(users.values()) if users else 0,
            "minimum_interactions_per_item": min(items.values()) if items else 0,
            "vendors": len({value[0] for value in products.values()}), "sessions": len(sessions),
            "items_with_multiple_names": len(name_conflicts),
            "items_with_multiple_vendors": len(vendor_conflicts),
            "session_user_conflicting_rows": session_conflicts,
            "timestamp_min": minimum_time if rows else None,
            "timestamp_max": maximum_time if rows else None,
            "time_span_days": (maximum_time - minimum_time) / 86400 if rows else None,
            "blank_cells": dict(missing)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/hyperhawkes-dhrd"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "dhrd.inter"
    if not target.exists():
        temporary = args.output_dir / "dhrd.inter.part"
        with temporary.open("xb") as stream:
            with urllib.request.urlopen(URL, timeout=60) as response:
                if "text/html" in response.headers.get("Content-Type", ""):
                    raise ValueError("Source returned HTML instead of data")
                received = 0
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > EXPECTED_BYTES:
                        raise ValueError("Source exceeded expected file size")
                    stream.write(chunk)
        verified_hashes(temporary)
        publish_new(temporary, target)
        temporary.unlink()
    sha256 = verified_hashes(target)
    manifest = {"data_kind": "real_preprocessed_derivative", "source_url": URL,
                "source_repository": "https://github.com/dbis-uibk/HyperHawkes",
                "original_dataset": "https://github.com/deliveryhero/dh-reco-dataset",
                "revision": REVISION, "git_blob_sha1": EXPECTED_GIT_BLOB,
                "bytes": EXPECTED_BYTES, "sha256": sha256, "profile": profile(target),
                "limitations": ["Preprocessed academic derivative, not the original DHRD release.",
                                "Fields and populations may differ from the original dataset.",
                                "No fabricated products or inferred metadata added."]}
    report = args.output_dir / "manifest.json"
    report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
