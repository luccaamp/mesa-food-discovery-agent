import argparse
import json
from pathlib import Path
from meal_discovery.deployment import fetch_artifact

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch exact SHA-pinned serving artifacts during image build")
    parser.add_argument("--manifest", type=Path, default=Path("deploy/catalog-serving-sg-v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    print(json.dumps(fetch_artifact(args.manifest, args.output_dir), indent=2))
