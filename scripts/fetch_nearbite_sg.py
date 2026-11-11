"""Download public third-party Singapore DHRD copies; no synthetic fallback."""

import argparse
import concurrent.futures
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from meal_discovery.file_publish import publish_new
from pathlib import Path
import urllib.request

SOURCE_REVISION = "a58e7255e22fbf7ed60f4854c041a41ba5a5c454"
SOURCE = f"https://github.com/jpchawanda1/nearbite-recommender/blob/{SOURCE_REVISION}/scripts/download_data.py"
FILES = {
    "vendors_sg_clean.csv": {
        "id": "1FPYHV73PfNmC3p8AZEYeyoatJy9XUbAE", "bytes": 491_847,
        "columns": ["Unnamed: 0", "vendor_id", "chain_id", "geohash", "primary_cuisine", "latitude", "longitude"],
    },
    "products_sg.csv": {
        "id": "13V5LUuQB8-VTZX45Eh_UynuQ0ZatAebf", "bytes": 65_265_976,
        "columns": ["", "vendor_id", "product_id", "name", "unit_price"],
    },
    "orders_sg_train_clean.csv": {
        "id": "1ag0k8lzUWQ8J-CopiR4fjN_qv60ErLll", "bytes": 353_603_099,
        "columns": ["Unnamed: 0", "customer_id", "geohash", "order_id", "vendor_id", "product_id",
                    "day_of_week", "order_time", "order_day", "latitude", "longitude"],
    },
}


def inspect_file(path: Path, expected: dict) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    if size != expected["bytes"]:
        raise ValueError(f"Unexpected size: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), [])
    if header != expected["columns"]:
        raise ValueError(f"Unexpected CSV header: {path.name}")
    return {"file": path.name, "bytes": size, "sha256": digest.hexdigest(), "columns": header}


def fetch(directory: Path, name: str, expected: dict) -> dict:
    url = f"https://drive.usercontent.google.com/download?id={expected['id']}&export=download&confirm=t"
    destination = directory / name
    if not destination.exists():
        print(f"Downloading {name} ({expected['bytes']} bytes)", flush=True)
        partial = directory / (name + ".part")
        with urllib.request.urlopen(url, timeout=60) as response:
            if "accounts.google.com" in response.url or "text/html" in response.headers.get("Content-Type", ""):
                raise ValueError(f"File is not publicly downloadable: {name}")
            first = response.read(8192)
            actual_header = next(csv.reader(io.StringIO(first.split(b"\n", 1)[0].decode("utf-8-sig"))), [])
            if actual_header != expected["columns"]:
                raise ValueError(f"Source did not return expected CSV: {name}")
            received = len(first)
            with partial.open("xb") as stream:
                stream.write(first)
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > expected["bytes"]:
                        raise ValueError(f"Source exceeds expected size: {name}")
                    stream.write(chunk)
        inspect_file(partial, expected)
        publish_new(partial, destination)
        partial.unlink()
    result = inspect_file(destination, expected)
    result["source_url"] = url
    print(f"Verified size and header: {name}; SHA-256 {result['sha256']}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/nearbite-sg"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    previous_path = args.output_dir / "download-manifest.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else None
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(fetch, args.output_dir, name, expected) for name, expected in FILES.items()]
        files = [job.result() for job in jobs]
    if previous:
        old = {record["file"]: record["sha256"] for record in previous["files"]}
        if any(old.get(record["file"]) != record["sha256"] for record in files):
            raise ValueError("Local hashes differ from the previous download manifest")
    manifest = {
        "data_kind": "real_third_party_copy", "city": "Singapore", "source_code_url": SOURCE,
        "original_dataset": "https://github.com/deliveryhero/dh-reco-dataset",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(), "files": files,
        "limitations": ["Mirror claims DHRD origin; byte equivalence to original package is not verified.",
                        "Clean orders/vendors include coordinates derived from geohashes by the mirror author.",
                        "No original separate test file or other cities supplied by these links.",
                        "Recorded SHA-256 verifies repeatability, not independent certification of origin."],
    }
    previous_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Downloaded/verified {sum(item['bytes'] for item in files)} bytes. Manifest: {previous_path}", flush=True)


if __name__ == "__main__":
    main()
