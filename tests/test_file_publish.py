from pathlib import Path
import tempfile
import unittest

from meal_discovery.file_publish import publish_new


class PublishTests(unittest.TestCase):
    def test_completed_file_and_conflicting_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, other, destination = root / "first.tmp", root / "other.tmp", root / "artifact"
            first.write_bytes(b"complete artifact")
            other.write_bytes(b"conflicting writer")
            publish_new(first, destination)
            self.assertEqual(destination.read_bytes(), b"complete artifact")
            with self.assertRaises(FileExistsError):
                publish_new(other, destination)
            self.assertEqual(destination.read_bytes(), b"complete artifact")
            self.assertEqual(other.read_bytes(), b"conflicting writer")

    def test_failed_source_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "artifact"
            with self.assertRaises(FileNotFoundError):
                publish_new(Path(directory) / "absent.tmp", destination)
            self.assertFalse(destination.exists())
