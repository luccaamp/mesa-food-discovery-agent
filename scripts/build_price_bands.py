"""Build the versioned price-band artifact from the official catalog index."""

import argparse
import json
from pathlib import Path

from meal_discovery.pricing import ARTIFACT, build_bands

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/processed/singapore-catalog-v1.sqlite")
    parser.add_argument("--output", type=Path, default=ARTIFACT)
    args = parser.parse_args()
    print(json.dumps(build_bands(args.catalog, args.output)))
