import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from meal_discovery.dataset import open_dataset
from meal_discovery.benchmark import validate_singapore
from meal_discovery.recommendation import Recommender
from meal_discovery.singapore import parse_day, prepare_official_singapore, prepare_singapore

# Column contract of the Singapore CSV layout used to build synthetic test fixtures.
FILES = {
    "vendors_sg_clean.csv": {"columns": ["Unnamed: 0", "vendor_id", "chain_id", "geohash", "primary_cuisine",
                                         "latitude", "longitude"]},
    "products_sg.csv": {"columns": ["", "vendor_id", "product_id", "name", "unit_price"]},
    "orders_sg_train_clean.csv": {"columns": ["Unnamed: 0", "customer_id", "geohash", "order_id", "vendor_id",
                                              "product_id", "day_of_week", "order_time", "order_day", "latitude",
                                              "longitude"]},
}


def source_fixture(root):
    root.mkdir()
    records = {
        "vendors_sg_clean.csv": [["0", "v1", "", "geo", "category", "1", "2"]],
        "products_sg.csv": [["0", "v1", "p1", "Test one", "1"], ["1", "v1", "p2", "Test two", "2"]],
        "orders_sg_train_clean.csv": [
            ["0", "u1", "geo", "o1", "v1", "p1", "0", "12:00:00", "0 days", "1", "2"],
            ["1", "u1", "geo", "o1", "v1", "p1", "0", "12:00:00", "0 days", "1", "2"],
            ["2", "u2", "geo", "bad", "v1", "p1", "0", "13:00:00", "0 days", "1", "2"],
            ["3", "u2", "geo", "bad", "v1", "missing", "0", "13:00:00", "0 days", "1", "2"],
            ["4", "u1", "geo", "o3", "v1", "p2", "1", "12:00:00", "1 days", "1", "2"],
        ],
    }
    files = []
    for name, values in records.items():
        path = root / name
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FILES[name]["columns"])
            writer.writerows(values)
        files.append({"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (root / "download-manifest.json").write_text(json.dumps({"data_kind": "synthetic", "files": files}), encoding="utf-8")
    return {row["file"]: row["sha256"] for row in files}


class SingaporePreparationTests(unittest.TestCase):
    def test_official_preparation_does_not_open_or_import_the_test_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_fixture(root / "mirror")
            city = root / "official/data_sg"
            city.mkdir(parents=True)
            names = {"vendors_sg_clean.csv": "vendors_sg.txt", "products_sg.csv": "products_sg.txt",
                     "orders_sg_train_clean.csv": "orders_sg_train.txt"}
            files = []
            for source, target in names.items():
                (city / target).write_bytes((root / "mirror" / source).read_bytes())
                files.append({"path": "data_sg/" + target, "sha256": hashlib.sha256((city / target).read_bytes()).hexdigest()})
            files.append({"path": "data_sg/orders_sg_test.txt", "sha256": "unopened-test-reference"})
            manifest = {"data_kind": "synthetic", "archives": [{"city_code": "sg", "files": files}]}
            (root / "official/official-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = prepare_official_singapore(root / "official", root / "prepared.sqlite", allow_test_data=True)
            self.assertEqual(result["adapter_version"], "singapore-official-v1")
            self.assertFalse(result["official_test_reference"]["loaded_into_training_database"])
            self.assertFalse((city / "orders_sg_test.txt").exists())
            self.assertEqual(result["source_counts"]["orders"], 3)
            protocol = {"protocol_version": "singapore-official-validation-v2", "dataset_adapter": "singapore-official-v1",
                        "train_end_day_inclusive": 0, "validation_end_day_inclusive": 1,
                        "test_start_day_inclusive": 76, "test_end_day_inclusive": 90,
                        "k": 1, "models": ["popularity"], "max_users": None, "geographic_filter": False}
            path = root / "protocol.json"
            path.write_text(json.dumps(protocol), encoding="utf-8")
            validation = validate_singapore(root / "prepared.sqlite", path, allow_test_data=True)
            self.assertTrue(validation["reserved_test"]["stored_separately"])
            self.assertFalse(validation["reserved_test"]["evaluated"])

    def test_quarantines_whole_order_keeps_context_and_deduplicates_items(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = source_fixture(root / "raw")
            report = prepare_singapore(root / "raw", root / "prepared.sqlite", allow_test_data=True)
            self.assertEqual(report["quarantine"], {"policy": "exclude_whole_order", "orphan_item_lines": 1,
                                                   "excluded_orders": 1, "excluded_item_lines": 2})
            self.assertEqual(report["counts"]["orders"], 2)
            self.assertEqual(report["counts"]["order_items"], 2)
            self.assertEqual(report["deduplicated_item_lines"], 1)
            connection = open_dataset(root / "prepared.sqlite")
            try:
                self.assertIsNone(connection.execute("SELECT 1 FROM orders WHERE order_id='bad'").fetchone())
                self.assertEqual(connection.execute("SELECT geohash FROM order_context WHERE order_id='o1'").fetchone()[0], "geo")
                self.assertFalse(connection.execute("PRAGMA foreign_key_check").fetchall())
            finally:
                connection.close()
            self.assertEqual(before, {name: hashlib.sha256((root / "raw" / name).read_bytes()).hexdigest() for name in before})

    def test_synthetic_data_cannot_enter_public_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_fixture(root / "raw")
            with self.assertRaisesRegex(ValueError, "Real Singapore"):
                prepare_singapore(root / "raw", root / "prepared.sqlite")
            self.assertFalse((root / "prepared.sqlite").exists())

    def test_changed_source_is_rejected_before_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_fixture(root / "raw")
            with (root / "raw/products_sg.csv").open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "hashes"):
                prepare_singapore(root / "raw", root / "prepared.sqlite", allow_test_data=True)
            self.assertFalse((root / "prepared.sqlite").exists())

    def test_real_label_alone_does_not_replace_pinned_source_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_fixture(root / "raw")
            path = root / "raw/download-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["data_kind"] = "real_third_party_copy"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "audited Singapore"):
                prepare_singapore(root / "raw", root / "prepared.sqlite")
            self.assertFalse((root / "prepared.sqlite").exists())

    def test_conflicting_context_prevents_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_fixture(root / "raw")
            path = root / "raw/orders_sg_train_clean.csv"
            # Same order, conflicting location in one additional item line.
            with path.open("a", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerow(["9", "u1", "other", "o1", "v1", "p2", "0", "12:00:00", "0 days", "1", "2"])
            manifest_path = root / "raw/download-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest["files"]:
                if record["file"] == path.name:
                    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                prepare_singapore(root / "raw", root / "prepared.sqlite", allow_test_data=True)
            self.assertFalse((root / "prepared.sqlite").exists())
            self.assertFalse(list(root.glob("singapore-*.tmp")))

    def test_relative_day_is_not_silently_truncated(self):
        self.assertEqual(parse_day("75 days"), 75)
        self.assertEqual(parse_day("0 days 00:00:00"), 0)
        for invalid in ("1.5", "1 days 12:00:00", "-1 days", "tomorrow"):
            with self.assertRaises(ValueError):
                parse_day(invalid)

    def test_frozen_validation_keeps_test_days_unmeasured(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_fixture(root / "raw")
            path = root / "raw/orders_sg_train_clean.csv"
            with path.open("a", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerow(["8", "future-user", "geo", "o4", "v1", "p1", "2", "12:00:00", "2 days", "1", "2"])
            manifest_path = root / "raw/download-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest["files"]:
                if record["file"] == path.name:
                    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            prepare_singapore(root / "raw", root / "prepared.sqlite", allow_test_data=True)
            protocol = {"protocol_version": "singapore-next-basket-v1", "dataset_adapter": "singapore-v1",
                        "train_end_day_inclusive": 0, "validation_end_day_inclusive": 1,
                        "test_end_day_inclusive": 2, "k": 1, "models": ["popularity", "repeat", "basket_cosine"],
                        "max_users": None, "geographic_filter": False}
            config = root / "protocol.json"
            config.write_text(json.dumps(protocol), encoding="utf-8")
            result = validate_singapore(root / "prepared.sqlite", config, allow_test_data=True)
            self.assertEqual(result["evaluation"]["users"], 1)
            self.assertEqual(result["training"]["users"], 1)
            self.assertFalse(result["reserved_test"]["evaluated"])
            self.assertEqual(result["reserved_test"]["start_day_inclusive"], 2)
            self.assertEqual(result["models"]["popularity"]["recall"], 0)

    def test_basket_similarity_uses_co_purchases_and_unique_results(self):
        model = Recommender([("u1", {"a"}), ("u2", {"a", "b"}), ("u3", {"c"})],
                            include_user_similarity=False, include_basket_similarity=True)
        self.assertEqual(model.recommend("u1", "basket_cosine", 1), ["b"])
        self.assertEqual(model.recommend("new", "basket_cosine", 3), ["a", "b", "c"])
        self.assertEqual(len(set(model.recommend("u1", "basket_cosine", 10))), 3)

    def test_empty_co_purchase_graph_falls_back_without_inventing_affinity(self):
        model = Recommender([("u1", {"a"}), ("u2", {"b"})], include_basket_similarity=True)
        self.assertEqual(model.recommend("u1", "basket_cosine", 2), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
