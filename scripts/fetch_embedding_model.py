"""Fetch two pinned public inference files; keep all model weights outside Git."""

import argparse
import hashlib
import os
from meal_discovery.file_publish import publish_new
from pathlib import Path
import tempfile
from urllib.request import urlopen

from meal_discovery.dataset import file_hash
from meal_discovery.embeddings import MODEL_FILES, MODEL_REPOSITORY, MODEL_REVISION, verify_model


def fetch(directory):
    for name, expected in MODEL_FILES.items():
        destination = directory / name
        if destination.exists():
            if destination.stat().st_size == expected["bytes"] and file_hash(destination) == expected["sha256"]:
                continue
            raise ValueError("Existing model file differs; choose another output directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix="e5-", suffix=".part", dir=destination.parent)
        temporary = Path(filename)
        try:
            digest = hashlib.sha256()
            total = 0
            with os.fdopen(handle, "wb") as stream, urlopen(
                    f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/{MODEL_REVISION}/{name}", timeout=60) as response:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > expected["bytes"]:
                        raise ValueError("Model download exceeds its pinned size")
                    digest.update(chunk)
                    stream.write(chunk)
            if total != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
                raise ValueError("Model download integrity failure")
            publish_new(temporary, destination)
            print(f"Verified {name}: {total:,} bytes", flush=True)
        finally:
            temporary.unlink(missing_ok=True)
    verify_model(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("models/e5-small-onnx-v1"))
    fetch(parser.parse_args().output_dir)
