import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import audit_official_data as auditor
from scripts import verify_official_archives as verifier


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


class OfficialDataAuditTests(unittest.TestCase):
    def test_manifest_cannot_omit_a_city_or_reference_unexpected_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "official-manifest.json"
            manifest.write_text(json.dumps({"archives": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "each official city"):
                auditor.verify_manifest(root)
            # A path outside the allowed member list is rejected before any read.
            data = {"archives": [{"city_code": "sg", "archive_sha256": "fixture",
                                    "files": [{"path": "../outside", "sha256": "unknown"}]}]}
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with patch.dict(auditor.ARCHIVE_HASHES, {"sg": "fixture"}, clear=True):
                with self.assertRaisesRegex(ValueError, "unexpected"):
                    auditor.verify_manifest(root)

    def test_common_fields_match_while_export_index_and_coordinates_differ(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_csv(root / "original.txt", ["", "id", "value"], [[0, "u1", "one"], [1, "u2", "two"]])
            write_csv(root / "mirror.csv", ["Unnamed: 0", "id", "value", "latitude"], [[0, "u1", "one", 1], [1, "u2", "two", 2]])
            result = auditor.compare_common_fields(root / "original.txt", root / "mirror.csv", ("id", "value"))
            self.assertTrue(result["same_common_fields_and_order"])
            self.assertTrue(result["same_row_multiset_fingerprint"])
            self.assertNotIn("u1", json.dumps(result))

    def test_multiset_check_distinguishes_reordering_from_changed_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_csv(root / "a.csv", ["id"], [["a"], ["b"]])
            write_csv(root / "b.csv", ["id"], [["b"], ["a"]])
            result = auditor.compare_common_fields(root / "a.csv", root / "b.csv", ("id",))
            self.assertFalse(result["same_common_fields_and_order"])
            self.assertTrue(result["same_row_multiset_fingerprint"])
            write_csv(root / "b.csv", ["id"], [["a"], ["a"]])
            result = auditor.compare_common_fields(root / "a.csv", root / "b.csv", ("id",))
            self.assertFalse(result["same_row_multiset_fingerprint"])

    def test_split_audit_checks_union_overlap_and_missing_catalog_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            city = root / "data_sg"
            train = ("u1", "geo", "o1", "v1", "p1", "0", "12:00:00", "0 days")
            test = ("u2", "geo", "o2", "v1", "missing", "1", "12:00:00", "76 days")
            write_csv(city / "vendors_sg.txt", auditor.VENDOR_FIELDS, [("v1", "", "geo", "category")])
            write_csv(city / "products_sg.txt", auditor.PRODUCT_FIELDS, [("v1", "p1", "Test item", "1")])
            for suffix, values in (("_train", [train]), ("_test", [test]), ("", [test, train])):
                write_csv(city / f"orders_sg{suffix}.txt", auditor.ORDER_FIELDS, values)
            result = auditor.audit_city(root, "sg", root)
            self.assertEqual(result["splits"]["train"]["orders"], 1)
            self.assertEqual(result["splits"]["test"]["order_lines_without_product"], 1)
            self.assertTrue(result["split_checks"]["train_test_multiset_matches_full"])
            self.assertEqual(result["split_checks"]["overlapping_order_ids"], 0)
            write_csv(city / "orders_sg_test.txt", auditor.ORDER_FIELDS, [train])
            write_csv(city / "orders_sg.txt", auditor.ORDER_FIELDS, [train, train])
            with self.assertRaisesRegex(ValueError, "consistency"):
                auditor.audit_city(root, "sg", root)


class OfficialArchiveTests(unittest.TestCase):
    def archive(self, root, extra=None):
        path = root / "data_sg.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for member in sorted(verifier.expected_members("sg")):
                archive.writestr(member, "id\n1\n")
            if extra:
                archive.writestr(extra, "not allowed")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_verified_package_extracts_and_existing_sources_are_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = self.archive(root)
            with patch.dict(verifier.ARCHIVE_HASHES, {"sg": digest}, clear=True):
                result = verifier.verify_extract(root, root / "output")
                self.assertEqual(len(result["archives"][0]["files"]), 5)
                target = root / "output/data_sg/products_sg.txt"
                target.write_text("existing source changed", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "differs"):
                    verifier.verify_extract(root, root / "output")
                self.assertEqual(target.read_text(encoding="utf-8"), "existing source changed")

    def test_unexpected_paths_cannot_be_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = self.archive(root, "../outside.txt")
            with patch.dict(verifier.ARCHIVE_HASHES, {"sg": digest}, clear=True):
                with self.assertRaisesRegex(ValueError, "Unexpected"):
                    verifier.verify_extract(root, root / "output")
            self.assertFalse((root / "outside.txt").exists())

    def test_preexisting_partial_file_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = self.archive(root)
            partial = root / "output/data_sg/orders_sg.txt.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"existing partial")
            with patch.dict(verifier.ARCHIVE_HASHES, {"sg": digest}, clear=True):
                with self.assertRaises(FileExistsError):
                    verifier.verify_extract(root, root / "output")
            self.assertEqual(partial.read_bytes(), b"existing partial")


if __name__ == "__main__":
    unittest.main()
