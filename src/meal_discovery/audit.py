"""Streaming inventory for CSVs; does not assume an unverified DHRD schema."""

import csv
import hashlib
from pathlib import Path


def audit_csv(path: Path, *, encoding: str = "utf-8-sig", delimiter: str = ",") -> dict:
    """Count records and missing cells without including row contents in output."""
    if len(delimiter) != 1:
        raise ValueError("Delimiter must be one character")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    with path.open(encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        header = next(reader, None)
        if not header or any(not name.strip() for name in header):
            raise ValueError(f"Missing or blank column names: {path.name}")
        if len(set(header)) != len(header):
            raise ValueError(f"Duplicate column names: {path.name}")
        missing = [0] * len(header)
        rows = 0
        malformed = 0
        for row in reader:
            rows += 1
            if len(row) != len(header):
                malformed += 1
                continue
            for index, value in enumerate(row):
                missing[index] += int(not value.strip())
    return {
        "file": path.name,
        "sha256": digest.hexdigest(),
        "bytes": path.stat().st_size,
        "columns": header,
        "rows": rows,
        "malformed_width_rows": malformed,
        "blank_cells_in_valid_width_rows": dict(zip(header, missing)),
    }


def audit_directory(directory: Path, **options) -> dict:
    if not directory.is_dir():
        raise ValueError("Input must be an existing directory")
    files = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".csv")
    if not files:
        raise ValueError("No CSV files found; obtain and extract the source data first")
    inventory = []
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Input files must resolve inside the input directory")
        result = audit_csv(path, **options)
        result["file"] = path.relative_to(directory).as_posix()
        inventory.append(result)
    return {"schema_version": 1, "files": inventory}
