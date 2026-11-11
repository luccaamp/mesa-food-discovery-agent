"""Publish completed local files atomically without replacing existing artifacts."""
import os
from pathlib import Path


def publish_new(source: Path, destination: Path):
    """Publish on the same filesystem; caller owns cleanup of the temporary file.

    Windows rename fails if the destination exists, including a racing writer.
    POSIX rename would replace it, so use an exclusive hard link there instead.
    No copy fallback: a partially written destination must never become visible.
    """
    if os.name == "nt":
        os.rename(source, destination)
    else:
        os.link(source, destination)
