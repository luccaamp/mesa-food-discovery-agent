import hashlib
import tempfile
import unittest
from pathlib import Path

from meal_discovery.audit import audit_csv, audit_directory


class AuditIntegrityTests(unittest.TestCase):
    def test_counts_csv_records_including_quoted_newlines_and_bad_width(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.csv"
            content = 'id,name\n1,"rice\nand tea"\n2,\n3,extra,value\n'
            path.write_text(content, encoding="utf-8", newline="")
            result = audit_csv(path)
            self.assertEqual(result["rows"], 3)
            self.assertEqual(result["malformed_width_rows"], 1)
            self.assertEqual(result["blank_cells_in_valid_width_rows"]["name"], 1)
            self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertNotIn("rice", str(result))

    def test_rejects_duplicate_headers_and_missing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                audit_directory(root)
            path = root / "sample.csv"
            path.write_text("id,id\n1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                audit_csv(path)

    def test_nested_files_keep_distinct_relative_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for city in ("a", "b"):
                (root / city).mkdir()
                (root / city / "orders.csv").write_text("id\n1\n", encoding="utf-8")
            result = audit_directory(root)
            self.assertEqual([f["file"] for f in result["files"]], ["a/orders.csv", "b/orders.csv"])


if __name__ == "__main__":
    unittest.main()
