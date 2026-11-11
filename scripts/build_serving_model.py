import argparse
import json
from pathlib import Path

from meal_discovery.serving import build_serving

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fit real co-basket serving artifact through day 61, without test orders")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_serving(args.database, args.output, progress=lambda message: print(message, flush=True))
    print(json.dumps(result, indent=2))
