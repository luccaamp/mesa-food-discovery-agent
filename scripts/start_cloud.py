"""Start the immutable public demo: no training, model or data downloads."""

import json
import os
from pathlib import Path
import sqlite3

import uvicorn

from meal_discovery.catalog import catalog_metadata
from meal_discovery.deployment import CATALOG, SERVING


def verify_startup():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "deploy/catalog-serving-sg-v1.json").read_text(encoding="utf-8"))
    directory = root / "data/processed"
    # Full SHA256/integrity checks run at build time. At startup check immutable files
    # and source pairing without scanning 570 MB on every wake-up.
    for name in (CATALOG, SERVING):
        if (directory / name).stat().st_size != manifest["files"][name]["bytes"]:
            raise ValueError("Deployment artifact size differs")
    catalog = catalog_metadata(directory / CATALOG)
    connection = sqlite3.connect((directory / SERVING).as_uri() + "?mode=ro", uri=True)
    try:
        serving = json.loads(connection.execute("SELECT value FROM metadata WHERE key='serving_manifest'").fetchone()[0])
    finally:
        connection.close()
    if (catalog["source_database_sha256"] != manifest["provenance"]["source_database_sha256"]
            or serving["source_database_sha256"] != catalog["source_database_sha256"]):
        raise ValueError("Deployment source pairing differs")
    if not (root / "apps/web/dist/index.html").is_file():
        raise ValueError("Built interface missing")
    if os.environ.get("MEAL_PUBLIC_MODE") != "1":
        raise ValueError("Public admission limits must be enabled")
    return root


if __name__ == "__main__":
    root = verify_startup()
    os.chdir(root)
    port = int(os.environ.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PORT")
    uvicorn.run("meal_discovery.api:app", host="0.0.0.0", port=port, workers=1,
                access_log=False, limit_concurrency=12, timeout_keep_alive=5)
