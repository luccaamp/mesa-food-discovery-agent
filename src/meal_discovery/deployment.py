"""Verify and distribute only the two read-only public serving artifacts."""

import hashlib
import json
import os
from .file_publish import publish_new
from pathlib import Path
import shutil
import sqlite3
import tempfile
from urllib.request import urlopen
import zipfile

from .catalog import catalog_metadata
from .dataset import file_hash

CATALOG = "singapore-catalog-v1.sqlite"
SERVING = "singapore-serving-v1.sqlite"
NOTICE = "DATA-NOTICE.txt"
ASSET_URL = "https://github.com/luccaamp/mesa/releases/download/mesa-data-sg-v1/catalog-serving-sg-v1.zip"


def validate_directory(directory, *, allow_test_data=False):
    catalog = catalog_metadata(directory / CATALOG, allow_test_data=allow_test_data)
    expected_tables = {
        CATALOG: {"metadata", "items", "item_search", "item_search_data", "item_search_idx", "item_search_docsize", "item_search_config"},
        SERVING: {"metadata", "items", "popularity", "neighbors"},
    }
    for name, expected in expected_tables.items():
        connection = sqlite3.connect((directory / name).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables != expected:
                raise ValueError("Unexpected tables in serving artifacts; do not publish source order/customer databases")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Artifact database integrity check failed")
            if name == SERVING:
                serving = json.loads(connection.execute("SELECT value FROM metadata WHERE key='serving_manifest'").fetchone()[0])
        finally:
            connection.close()
    if (serving.get("artifact_version") != "basket-serving-v1" or serving.get("data_kind") != catalog.get("data_kind")
            or serving.get("source_database_sha256") != catalog.get("source_database_sha256")
            or serving.get("train_end_day_inclusive") != 61):
        raise ValueError("Catalog and serving artifact origins differ")
    return {"data_kind": catalog["data_kind"], "city": catalog["city"], "products": catalog["products"],
            "cuisines": catalog["cuisines"], "source_database_sha256": catalog["source_database_sha256"],
            "source_hashes": catalog["source_hashes"], "training_orders": serving["training_orders"],
            "training_items": serving["training_items"], "neighbor_edges": serving["neighbor_edges"],
            "train_end_day_inclusive": 61, "individual_order_or_customer_tables": False}


def package_artifact(directory, notice, archive, manifest_path, *, allow_test_data=False):
    if archive.exists() or manifest_path.exists():
        raise ValueError("Choose new artifact and manifest output paths")
    provenance = validate_directory(directory, allow_test_data=allow_test_data)
    sources = {CATALOG: directory / CATALOG, SERVING: directory / SERVING, NOTICE: notice}
    files = {name: {"bytes": path.stat().st_size, "sha256": file_hash(path)} for name, path in sources.items()}
    archive.parent.mkdir(parents=True, exist_ok=True)
    handle, filename = tempfile.mkstemp(prefix="mesa-package-", suffix=".tmp", dir=archive.parent)
    os.close(handle)
    temporary = Path(filename)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for name, path in sources.items():
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open("rb") as source, zipped.open(info, "w", force_zip64=True) as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
        if files != {name: {"bytes": path.stat().st_size, "sha256": file_hash(path)} for name, path in sources.items()}:
            raise ValueError("Sources changed during packaging")
        result = {"artifact_version": "mesa-public-data-v1", "download_url": ASSET_URL,
                  "bytes": temporary.stat().st_size, "sha256": file_hash(temporary), "files": files,
                  "provenance": provenance}
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        publish_new(temporary, archive)
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        return result
    finally:
        temporary.unlink(missing_ok=True)


def extract_artifact(archive, manifest, output, *, allow_test_data=False):
    if set(manifest.get("files", {})) != {CATALOG, SERVING, NOTICE}:
        raise ValueError("Artifact manifest must contain exactly the allowed serving files")
    if archive.stat().st_size != manifest["bytes"] or file_hash(archive) != manifest["sha256"]:
        raise ValueError("Artifact archive checksum mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="mesa-artifact-", dir=output.parent))
    try:
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            if len(members) != 3 or {member.filename for member in members} != set(manifest["files"]):
                raise ValueError("Unexpected or duplicate archive members")
            for member in members:
                expected = manifest["files"][member.filename]
                if member.file_size != expected["bytes"]:
                    raise ValueError("Unexpected artifact member size")
                path = temporary / member.filename
                with zipped.open(member) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                if file_hash(path) != expected["sha256"]:
                    raise ValueError("Extracted artifact checksum mismatch")
        provenance = validate_directory(temporary, allow_test_data=allow_test_data)
        if provenance != manifest["provenance"]:
            raise ValueError("Extracted provenance differs from release manifest")
        # Check every existing target before publishing any new file.
        for name, expected in manifest["files"].items():
            target = output / name
            if target.exists() and (target.stat().st_size != expected["bytes"] or file_hash(target) != expected["sha256"]):
                raise ValueError("Existing artifact differs; it was not overwritten")
        output.mkdir(parents=True, exist_ok=True)
        for name in manifest["files"]:
            if not (output / name).exists():
                publish_new(temporary / name, output / name)
        return provenance
    finally:
        if not temporary.resolve().is_relative_to(output.parent.resolve()) or not temporary.name.startswith("mesa-artifact-"):
            raise ValueError("Unsafe temporary cleanup target")
        shutil.rmtree(temporary)


def fetch_artifact(manifest_path, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_version") != "mesa-public-data-v1" or manifest.get("download_url") != ASSET_URL:
        raise ValueError("Unsupported deployment artifact source")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, filename = tempfile.mkstemp(prefix="mesa-download-", suffix=".zip", dir=output.parent)
    temporary = Path(filename)
    try:
        count, digest = 0, hashlib.sha256()
        with os.fdopen(handle, "wb") as target, urlopen(ASSET_URL, timeout=60) as response:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                count += len(chunk)
                if count > manifest["bytes"]:
                    raise ValueError("Artifact download exceeds pinned size")
                digest.update(chunk)
                target.write(chunk)
        if count != manifest["bytes"] or digest.hexdigest() != manifest["sha256"]:
            raise ValueError("Artifact download integrity failure")
        return extract_artifact(temporary, manifest, output)
    finally:
        temporary.unlink(missing_ok=True)
