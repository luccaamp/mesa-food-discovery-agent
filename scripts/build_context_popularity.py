"""Build the versioned region x time-slot popularity artifact from the official training orders."""

import argparse
import json
from pathlib import Path

from meal_discovery.context_popularity import ARTIFACT, build

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/singapore-official-v1.sqlite")
    parser.add_argument("--output", type=Path, default=ARTIFACT)
    args = parser.parse_args()
    print(json.dumps(build(args.database, args.output)))
