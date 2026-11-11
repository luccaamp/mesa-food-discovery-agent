import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from meal_discovery.catalog import build_catalog
from meal_discovery.deployment import CATALOG, SERVING, extract_artifact, package_artifact, validate_directory
from meal_discovery.serving import build_serving
from meal_discovery.singapore import prepare_singapore
from test_singapore import source_fixture


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source_fixture(self.root / "raw")
        dataset = self.root / "source.sqlite"
        prepare_singapore(self.root / "raw", dataset, allow_test_data=True)
        self.data = self.root / "data"
        self.data.mkdir()
        build_catalog(dataset, self.data / CATALOG, allow_test_data=True)
        build_serving(dataset, self.data / SERVING, allow_test_data=True)
        self.notice = self.root / "notice.txt"
        self.notice.write_text("Test attribution", encoding="utf-8")
        self.archive = self.root / "artifact.zip"
        self.manifest_path = self.root / "artifact.json"

    def package(self):
        return package_artifact(self.data, self.notice, self.archive, self.manifest_path, allow_test_data=True)

    def test_checksums_roundtrip_and_existing_files_are_not_overwritten(self):
        manifest = self.package()
        output = self.root / "extracted"
        provenance = extract_artifact(self.archive, manifest, output, allow_test_data=True)
        self.assertEqual(provenance, manifest["provenance"])
        self.assertFalse(provenance["individual_order_or_customer_tables"])
        self.assertEqual(json.loads(self.manifest_path.read_text()), manifest)
        extract_artifact(self.archive, manifest, output, allow_test_data=True)
        (output / CATALOG).write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "not overwritten"):
            extract_artifact(self.archive, manifest, output, allow_test_data=True)
        self.assertEqual((output / CATALOG).read_bytes(), b"existing")

    def test_archive_tampering_and_path_names_fail_before_extraction(self):
        manifest = self.package()
        manifest["files"]["../source.sqlite"] = manifest["files"].pop(CATALOG)
        with self.assertRaises(ValueError):
            extract_artifact(self.archive, manifest, self.root / "bad", allow_test_data=True)
        manifest = json.loads(self.manifest_path.read_text())
        with self.archive.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "checksum"):
            extract_artifact(self.archive, manifest, self.root / "bad", allow_test_data=True)
        self.assertFalse((self.root / "bad").exists())

    def test_source_order_tables_and_synthetic_data_block_public_packaging(self):
        with self.assertRaises(ValueError):
            validate_directory(self.data)
        connection = sqlite3.connect(self.data / SERVING)
        connection.execute("CREATE TABLE orders(customer_id TEXT)")
        connection.close()
        with self.assertRaisesRegex(ValueError, "Unexpected tables"):
            self.package()
        self.assertFalse(self.archive.exists())
