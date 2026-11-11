"""Explicit pinned GGUF/runtime download. No installer, system service or remote code."""

import hashlib
import argparse
import json
import os
from meal_discovery.file_publish import publish_new
from pathlib import Path, PurePosixPath
import tempfile
from urllib.request import urlopen
import zipfile

from meal_discovery.dataset import file_hash

ROOT = Path(__file__).resolve().parents[1]


def download(url, destination, expected):
    if destination.exists():
        if destination.stat().st_size == expected["bytes"] and file_hash(destination) == expected["sha256"]:
            return
        raise ValueError("Existing file differs from the pinned artifact")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, filename = tempfile.mkstemp(prefix="llm-", suffix=".part", dir=destination.parent)
    temporary = Path(filename)
    try:
        digest = hashlib.sha256()
        count = 0
        with os.fdopen(handle, "wb") as stream, urlopen(url, timeout=60) as response:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                count += len(chunk)
                if count > expected["bytes"]:
                    raise ValueError("Download exceeds expected size")
                digest.update(chunk)
                stream.write(chunk)
        if count != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
            raise ValueError("Artifact checksum mismatch")
        publish_new(temporary, destination)
        print(f"Verified {destination.name}: {count:,} bytes", flush=True)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    config = json.loads((ROOT / "configs/local-llm-v1.json").read_text(encoding="utf-8"))
    model = ROOT / "models/qwen-local-v1" / config["file"]
    download(f"https://huggingface.co/{config['repository']}/resolve/{config['revision']}/{config['file']}", model, config)
    runtime = config["runtime"]
    directory = ROOT / ".tools" / ("llama-" + runtime["tag"])
    archive = directory / runtime["file"]
    download(f"https://github.com/{runtime['repository']}/releases/download/{runtime['tag']}/{runtime['file']}", archive, runtime)
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename or ":" in member.filename:
                raise ValueError("Unsafe runtime archive path")
            if member.is_dir() or not (path.suffix == ".dll" or path.name == "llama-server.exe"):
                continue
            if len(path.parts) != 1 or member.file_size > 100 * 1024 * 1024:
                raise ValueError("Unexpected runtime member")
            destination = directory / path.name
            content = zipped.read(member)
            if destination.exists():
                if file_hash(destination) != hashlib.sha256(content).hexdigest():
                    raise ValueError("Existing runtime member differs")
            else:
                with destination.open("xb") as stream:
                    stream.write(content)
    if not (directory / "llama-server.exe").is_file():
        raise ValueError("Runtime server executable missing")
    print("Local model and CPU runtime ready; nothing was started automatically.")
