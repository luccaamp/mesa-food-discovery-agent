import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.legacy import audit_nearbite_sg as auditor
from scripts.legacy import fetch_nearbite_sg as downloader


class SourceAcquisitionTests(unittest.TestCase):
    def test_unused_blank_index_header_is_preserved_and_hash_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "products.csv"
            content = b",vendor_id,product_id,name,unit_price\n0,v1,p1,Tea,1\n"
            path.write_bytes(content)
            expected = {"bytes": len(content), "columns": ["", "vendor_id", "product_id", "name", "unit_price"]}
            result = downloader.inspect_file(path, expected)
            self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
            with self.assertRaises(ValueError):
                downloader.inspect_file(path, {**expected, "bytes": len(content) + 1})

    def test_html_login_cannot_be_saved_as_a_csv(self):
        class LoginResponse:
            url = "https://accounts.google.com/signin"
            headers = {"Content-Type": "text/html"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(downloader.urllib.request, "urlopen", return_value=LoginResponse()):
                with self.assertRaisesRegex(ValueError, "not publicly downloadable"):
                    downloader.fetch(Path(folder), "vendors.csv", {"id": "test", "bytes": 1})
            self.assertFalse(list(Path(folder).iterdir()))

    def test_relational_audit_reports_orphan_item_without_inventing_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = {
                "vendors_sg_clean.csv": [["0", "v1", "", "cell", "category", "", ""]],
                "products_sg.csv": [["0", "v1", "p1", "Test tea", "1"]],
                "orders_sg_train_clean.csv": [
                    ["0", "u1", "cell", "o1", "v1", "p1", "0", "12:00:00", "0 days", "", ""],
                    ["1", "u1", "cell", "o1", "v1", "absent", "0", "12:00:00", "0 days", "", ""],
                ],
            }
            expected = {}
            files = []
            for name, spec in downloader.FILES.items():
                path = root / name
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(spec["columns"])
                    writer.writerows(rows[name])
                content = path.read_bytes()
                expected[name] = {**spec, "bytes": len(content)}
                files.append({"file": name, "sha256": hashlib.sha256(content).hexdigest()})
            (root / "download-manifest.json").write_text(json.dumps({"files": files, "limitations": []}), encoding="utf-8")
            with patch.dict(auditor.FILES, expected, clear=True):
                result = auditor.audit(root, root)
            self.assertEqual(result["counts"]["orders"], 1)
            self.assertEqual(result["counts"]["order_item_rows"], 2)
            self.assertEqual(result["counts"]["distinct_products"], 1)
            self.assertEqual(result["integrity"]["order_rows_without_catalog_product"], 1)
            self.assertEqual(result["integrity"]["orders_with_conflicting_customer_day_or_time"], 0)
            self.assertFalse(list(root.glob("sg-audit-*")))


if __name__ == "__main__":
    unittest.main()
