import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from meal_discovery.benchmark import benchmark as real_benchmark, ranking_metrics
from meal_discovery.dataset import open_dataset, prepare_dataset as real_prepare_dataset
from synthetic_support import write_synthetic_source
from meal_discovery.recommendation import Recommender


def prepare_dataset(config, output):
    return real_prepare_dataset(config, output, allow_test_data=True)


def benchmark(database, **options):
    return real_benchmark(database, allow_test_data=True, **options)


class DatasetContractTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.config = write_synthetic_source(self.root / "raw")
        self.database = self.root / "dataset.sqlite"

    def append_row(self, table, row):
        with (self.root / "raw" / f"{table}.csv").open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow(row)

    def test_basket_rows_do_not_multiply_orders_and_identical_lines_are_deduplicated(self):
        self.append_row("orders", ("o2", "u2", "v1", "b", 0, "13:00:00"))
        report = prepare_dataset(self.config, self.database)
        self.assertEqual(report["counts"]["orders"], 6)
        self.assertEqual(report["counts"]["order_items"], 7)
        self.assertEqual(report["repeated_keys"]["order_items"], 1)
        self.assertEqual(report["data_kind"], "synthetic")

    def test_conflicting_order_metadata_fails_without_publishing_dataset(self):
        self.append_row("orders", ("o1", "different-customer", "v1", "a", 0, "12:00:00"))
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            prepare_dataset(self.config, self.database)
        self.assertFalse(self.database.exists())
        self.assertFalse(list(self.root.glob("dataset-*.tmp")))

    def test_orphan_product_reference_fails(self):
        self.append_row("orders", ("o7", "u1", "v1", "missing", 1, "12:00:00"))
        with self.assertRaisesRegex(ValueError, "integrity"):
            prepare_dataset(self.config, self.database)
        self.assertFalse(self.database.exists())

    def test_product_key_includes_vendor(self):
        self.append_row("vendors", ("v2", "category"))
        self.append_row("products", ("v2", "a", "Different vendor item", 2))
        report = prepare_dataset(self.config, self.database)
        self.assertEqual(report["counts"]["products"], 5)

    def test_nan_prices_rejected(self):
        self.append_row("products", ("v1", "bad", "Invalid price item", "nan"))
        with self.assertRaisesRegex(ValueError, "finite"):
            prepare_dataset(self.config, self.database)

    def test_missing_mapping_rejected(self):
        config = json.loads(self.config.read_text(encoding="utf-8"))
        del config["tables"]["orders"]["columns"]["order_day"]
        self.config.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mapping"):
            prepare_dataset(self.config, self.database)

    def test_existing_database_is_not_replaced(self):
        self.database.write_bytes(b"existing artifact")
        with self.assertRaisesRegex(ValueError, "exists"):
            prepare_dataset(self.config, self.database)
        self.assertEqual(self.database.read_bytes(), b"existing artifact")

    def test_dataset_is_opened_read_only(self):
        prepare_dataset(self.config, self.database)
        connection = open_dataset(self.database)
        try:
            import sqlite3
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM orders")
        finally:
            connection.close()


class RankingTests(unittest.TestCase):
    def test_metrics_match_hand_computed_ranking(self):
        import math
        metrics = ranking_metrics(["irrelevant", "b"], {"b", "unseen"}, 2)
        self.assertEqual(metrics["recall"], .5)
        self.assertAlmostEqual(metrics["ndcg"], (1 / math.log2(3)) / (1 + 1 / math.log2(3)))

    def test_duplicate_recommendations_cannot_inflate_metrics(self):
        with self.assertRaises(ValueError):
            ranking_metrics(["a", "a"], {"a"}, 2)

    def test_item_similarity_personalizes_and_cold_user_falls_back(self):
        model = Recommender([("u1", {"a"}), ("u2", {"a", "b"}), ("u3", {"c"})])
        self.assertEqual(model.recommend("u1", "item_cosine", 1), ["b"])
        self.assertEqual(model.recommend("new", "item_cosine", 2), model.recommend("new", "popularity", 2))
        self.assertEqual(len(set(model.recommend("u1", "repeat", 10))), 3)

    def test_validation_does_not_train_on_future_or_drop_unseen_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = write_synthetic_source(root / "raw")
            prepare_dataset(config, root / "dataset.sqlite")
            result = benchmark(root / "dataset.sqlite", train_end_day=1, eval_end_day=2, k=2)
            self.assertEqual(result["training"]["items"], 3)
            self.assertEqual(result["evaluation"]["users"], 2)
            self.assertEqual(result["evaluation"]["targets_outside_training_catalog"], 1)
            self.assertEqual(result["models"]["popularity"]["recall"], .5)
            self.assertEqual(result["models"]["popularity"]["segments"]["cold"]["recall"], 0)
            self.assertEqual(result["data_kind"], "synthetic")

    def test_future_rows_cannot_change_fixed_origin_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = write_synthetic_source(root / "raw")
            prepare_dataset(config, root / "before.sqlite")
            before = benchmark(root / "before.sqlite", train_end_day=1, eval_end_day=2, k=2)
            with (root / "raw/orders.csv").open("a", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                for i in range(20):
                    writer.writerow((f"later-{i}", f"user-{i}", "v1", "future", 10, "12:00:00"))
            prepare_dataset(config, root / "after.sqlite")
            after = benchmark(root / "after.sqlite", train_end_day=1, eval_end_day=2, k=2)
            self.assertEqual(before["evaluation"], after["evaluation"])
            for model in before["models"]:
                self.assertEqual(before["models"][model]["recall"], after["models"][model]["recall"])
                self.assertEqual(before["models"][model]["ndcg"], after["models"][model]["ndcg"])

    def test_empty_period_and_invalid_cutoffs_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = write_synthetic_source(root / "raw")
            prepare_dataset(config, root / "dataset.sqlite")
            with self.assertRaisesRegex(ValueError, "no baskets"):
                benchmark(root / "dataset.sqlite", train_end_day=5, eval_end_day=6)
            with self.assertRaises(ValueError):
                benchmark(root / "dataset.sqlite", train_end_day=2, eval_end_day=1)


class CommandLineTests(unittest.TestCase):
    def test_public_prepare_and_benchmark_reject_synthetic_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = write_synthetic_source(root / "raw")
            prefix = [sys.executable, "-m", "meal_discovery"]
            prepare = subprocess.run(prefix + ["prepare", "--config", str(config), "--output",
                                               str(root / "dataset.sqlite")], capture_output=True, text=True)
            self.assertEqual(prepare.returncode, 2)
            self.assertIn("Real data required", prepare.stderr)
            self.assertFalse((root / "dataset.sqlite").exists())
            prepare_dataset(config, root / "dataset.sqlite")
            command = prefix + ["benchmark", "--database", str(root / "dataset.sqlite"),
                                "--train-end-day", "1", "--eval-end-day", "2", "--k", "2",
                                "--output", str(root / "results.json")]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Real data required", result.stderr)
            self.assertFalse((root / "results.json").exists())

    def test_synthetic_demo_is_not_a_product_command(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "demo"
            command = [sys.executable, "-m", "meal_discovery", "demo", "--output-dir", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
