"""Verify and safely extract the three locally supplied official DHRD ZIPs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from meal_discovery.file_publish import publish_new
from pathlib import Path, PurePosixPath
import zipfile

ARCHIVE_HASHES = {
    "se": "2a3947bd29a892a634882b0ec45e4d47a09e68dfdc74fca353b53467eeb43da4",
    "sg": "55a94a5c7eeba9610776b864aae7d653426afdb8aae93e5fa5050cbdc1c25d32",
    "tw": "83e8c0f5bfb4c27f14e3dd13964cc72117975397d7bee2522336301eaed781ec",
}
REFERENCE_URL = "https://github.com/ISG-Siegen/OmniRec/blob/9800bd4e75d321d37be78de4d33ba72b73d8b92e/src/omnirec/data_loaders/deliveryhero.py"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_members(city):
    return {f"data_{city}/{name}_{city}{suffix}.txt"
            for name, suffix in (("orders", ""), ("orders", "_train"), ("orders", "_test"),
                                 ("products", ""), ("vendors", ""))}


def verify_extract(archive_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir.resolve()
    inventory = []
    for city, expected_hash in ARCHIVE_HASHES.items():
        archive = archive_dir / f"data_{city}.zip"
        digest = sha256(archive)
        if digest != expected_hash:
            raise ValueError(f"Archive differs from the recorded official-package reference: {archive.name}")
        print(f"Verified archive hash: {archive.name}", flush=True)
        with zipfile.ZipFile(archive) as source:
            selected = [item for item in source.infolist()
                        if not item.is_dir() and not item.filename.startswith("__MACOSX/")]
            if len(selected) != len(expected_members(city)) or {item.filename for item in selected} != expected_members(city):
                raise ValueError(f"Unexpected or duplicate archive members in {archive.name}")
            files = []
            for item in selected:
                relative = PurePosixPath(item.filename)
                target = (root / Path(*relative.parts)).resolve()
                if not target.is_relative_to(root) or relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                # Stream even when extracted file exists: validate CRC and compare content.
                temporary = target.with_name(target.name + ".part")
                h = hashlib.sha256()
                created_partial = False
                try:
                    with temporary.open("xb") as destination:
                        created_partial = True
                        with source.open(item) as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                h.update(chunk)
                                destination.write(chunk)
                    if temporary.stat().st_size != item.file_size:
                        raise ValueError("Extracted size mismatch")
                    if target.exists():
                        if sha256(target) != h.hexdigest():
                            raise ValueError(f"Existing extracted source differs: {target.name}")
                    else:
                        publish_new(temporary, target)
                    files.append({"path": item.filename, "bytes": item.file_size,
                                  "sha256": h.hexdigest(), "crc32": f"{item.CRC:08x}"})
                finally:
                    if created_partial:
                        temporary.unlink(missing_ok=True)
            inventory.append({"city_code": city, "archive": archive.name, "archive_bytes": archive.stat().st_size,
                              "archive_sha256": digest, "matches_reference": True,
                              "member_crc_verified": True, "files": files})
    manifest = {"data_kind": "official_dhrd", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": "User downloaded the three ZIPs from the official Drive folder.",
                "source_url": "https://drive.google.com/drive/folders/1dCUvFVmt9xNOGgadql_O16SwtGy6e_hE",
                "checksum_reference": REFERENCE_URL, "archives": inventory,
                "policy": "Read official test files for structural audit only; do not train/tune on their outcomes."}
    (root / "official-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/dhrd-official-v1"))
    args = parser.parse_args()
    result = verify_extract(args.archive_dir, args.output_dir)
    print(f"Verified/extracted {sum(len(city['files']) for city in result['archives'])} official text files.")


if __name__ == "__main__":
    main()
