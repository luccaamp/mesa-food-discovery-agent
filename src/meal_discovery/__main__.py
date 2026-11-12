"""Reproducible data preparation and recommendation experiments."""

import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

from .audit import audit_directory
from .benchmark import benchmark, validate_singapore
from .catalog import build_catalog, search_catalog
from .dataset import prepare_dataset
from .singapore import prepare_official_singapore, prepare_singapore


def write_report(path: Path, result: dict):
    if path.suffix.lower() != ".json":
        raise ValueError("Report must end in .json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Meal Discovery AI data tools")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Inventory extracted CSVs without exporting rows")
    audit.add_argument("--input-dir", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--encoding", default="utf-8-sig")
    audit.add_argument("--delimiter", default=",")
    prepare = commands.add_parser("prepare", help="Validate explicit CSV mappings and create a SQLite dataset")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    singapore = commands.add_parser("prepare-singapore", help="Prepare the pinned real Singapore mirror, quarantining whole invalid orders")
    singapore.add_argument("--input-dir", type=Path, default=Path("data/raw/nearbite-sg"))
    singapore.add_argument("--output", type=Path, required=True)
    official = commands.add_parser("prepare-official-singapore", help="Prepare only official training orders and catalog; leave official test separate")
    official.add_argument("--input-dir", type=Path, default=Path("data/raw/dhrd-official-v1"))
    official.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-singapore", help="Run the frozen validation protocol without evaluating reserved test days")
    validate.add_argument("--database", type=Path, required=True)
    validate.add_argument("--protocol", type=Path, default=Path("configs/singapore-official-experiment-v2.json"))
    validate.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser("benchmark", help="Evaluate fixed-origin next-basket recommendation")
    evaluate.add_argument("--database", type=Path, required=True)
    evaluate.add_argument("--train-end-day", type=int, required=True)
    evaluate.add_argument("--eval-end-day", type=int, required=True)
    evaluate.add_argument("--split", choices=("validation", "test"), default="validation")
    evaluate.add_argument("--k", type=int, default=10)
    evaluate.add_argument("--max-users", type=int)
    evaluate.add_argument("--output", type=Path, required=True)
    catalog = commands.add_parser("build-catalog", help="Index the official historical catalog for lexical search")
    catalog.add_argument("--database", type=Path, required=True)
    catalog.add_argument("--output", type=Path, required=True)
    search = commands.add_parser("search-catalog", help="Search real products with normalized-price and cuisine filters")
    search.add_argument("--index", type=Path, required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--cuisine")
    search.add_argument("--min-price", type=float)
    search.add_argument("--max-price", type=float)
    search.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    try:
        if args.command == "build-catalog":
            result = build_catalog(args.database, args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "search-catalog":
            result = search_catalog(args.index, args.query, cuisine=args.cuisine,
                                    min_price=args.min_price, max_price=args.max_price, limit=args.limit)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        elif args.command == "audit":
            if args.output.resolve().is_relative_to(args.input_dir.resolve()):
                raise ValueError("Store the report outside the source data directory")
            result = audit_directory(args.input_dir, encoding=args.encoding, delimiter=args.delimiter)
            write_report(args.output, result)
            print(f"Audited {len(result['files'])} CSV file(s). Report: {args.output}")
        elif args.command == "prepare":
            result = prepare_dataset(args.config, args.output)
            print(f"Dataset ({result['data_kind']}): {args.output}. Counts: {result['counts']}")
        elif args.command == "prepare-singapore":
            result = prepare_singapore(args.input_dir, args.output, progress=lambda message: print(message, file=sys.stderr, flush=True))
            print(f"Prepared real Singapore dataset: {args.output}. Counts: {result['counts']}. Quarantine: {result['quarantine']}")
        elif args.command == "prepare-official-singapore":
            result = prepare_official_singapore(args.input_dir, args.output, progress=lambda message: print(message, file=sys.stderr, flush=True))
            print(f"Prepared official training dataset: {args.output}. Counts: {result['counts']}. Official test rows were not loaded.")
        elif args.command == "validate-singapore":
            if args.output.exists() or args.output.suffix != ".json":
                raise ValueError("Choose a new .json validation report path")
            result = validate_singapore(args.database, args.protocol, progress=lambda message: print(message, file=sys.stderr, flush=True))
            write_report(args.output, result)
            print(f"Real-data validation report: {args.output}. Reserved test was not evaluated.")
        elif args.command == "benchmark":
            if args.output.exists() or args.output.suffix.lower() != ".json":
                raise ValueError("Choose a new .json report path")
            result = benchmark(args.database, train_end_day=args.train_end_day,
                               eval_end_day=args.eval_end_day, split=args.split, k=args.k,
                               max_users=args.max_users)
            write_report(args.output, result)
            print(f"Benchmark ({result['data_kind']}, {args.split}): {args.output}")
    except (OSError, UnicodeError, LookupError, ValueError, TypeError, csv.Error, sqlite3.Error) as error:
        parser.exit(2, f"Operation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
