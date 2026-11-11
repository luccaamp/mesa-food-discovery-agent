import argparse
import json
from pathlib import Path
from meal_discovery.deployment import package_artifact

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package verified public catalog and aggregated recommendation artifacts")
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("data/deploy/catalog-serving-sg-v1.zip"))
    parser.add_argument("--manifest", type=Path, default=Path("deploy/catalog-serving-sg-v1.json"))
    args = parser.parse_args()
    result = package_artifact(args.input_dir, Path("deploy/DATA-NOTICE.txt"), args.output, args.manifest)
    print(json.dumps({"bytes": result["bytes"], "sha256": result["sha256"], "provenance": result["provenance"]}, indent=2))
