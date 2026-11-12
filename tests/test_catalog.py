from pathlib import Path
import tempfile
import unittest

from meal_discovery.catalog import build_catalog, search_catalog
from meal_discovery.dataset import open_dataset
from meal_discovery.singapore import prepare_singapore
from test_singapore import source_fixture


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source_fixture(self.root / "raw")
        self.database = self.root / "source.sqlite"
        prepare_singapore(self.root / "raw", self.database, allow_test_data=True)
        self.index = self.root / "catalog.sqlite"
        self.manifest = build_catalog(self.database, self.index, allow_test_data=True)

    def search(self, query, **kwargs):
        return search_catalog(self.index, query, allow_test_data=True, **kwargs)

    def test_real_only_guard_and_source_is_unchanged(self):
        with self.assertRaisesRegex(ValueError, "official real"):
            search_catalog(self.index, "Test")
        with self.assertRaisesRegex(ValueError, "official real"):
            build_catalog(self.database, self.root / "rejected.sqlite")
        self.assertFalse((self.root / "rejected.sqlite").exists())
        connection = open_dataset(self.database)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 2)

    def test_rank_filters_no_match_and_historical_provenance(self):
        self.assertEqual(self.manifest["products"], 2)
        result = self.search("Test", min_price=2, max_price=2, cuisine="category")
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["items"][0]["product_id"], "p2")
        self.assertTrue(result["provenance"]["historical_catalog"])
        self.assertEqual(self.search("Test", cuisine="absent")["items"], [])
        self.assertEqual(self.search("absent")["total_matches"], 0)
        self.assertEqual(self.search("Test", limit=1)["total_matches"], 2)
        self.assertEqual(len(self.search("Test", limit=1)["items"]), 1)

    def test_ties_rank_items_with_a_recorded_price_first(self):
        # 28% of the official catalog records a price of 0; on equal relevance they must not lead.
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.index)) as connection, connection:
            connection.execute("UPDATE items SET unit_price=0 WHERE product_id='p1'")
        items = self.search("Test")["items"]
        self.assertEqual(items[0]["lexical_score"], items[1]["lexical_score"])
        self.assertEqual([item["product_id"] for item in items], ["p2", "p1"])
        # A recorded 0 means the price is missing, so a ceiling must not match it.
        self.assertEqual([item["product_id"] for item in self.search("Test", max_price=5)["items"]], ["p2"])

    def test_fts_syntax_and_sql_are_literal_search_terms(self):
        self.assertEqual(self.search('Test OR absent')["items"], [])
        self.assertEqual(self.search('"Test" AND one')["items"], [])
        self.assertEqual(self.search("'; DROP TABLE items; --")["items"], [])
        self.assertEqual(self.search("Test one")["total_matches"], 1)

    def test_invalid_bounds_queries_and_overwrite_are_rejected(self):
        for kwargs in ({"limit": 0}, {"limit": True}, {"min_price": float("nan")},
                       {"max_price": float("inf")}, {"min_price": -1},
                       {"min_price": 3, "max_price": 2}, {"cuisine": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.search("Test", **kwargs)
        for query in ("", "---", "x" * 201):
            with self.assertRaises(ValueError):
                self.search(query)
        with self.assertRaises(ValueError):
            build_catalog(self.database, self.index, allow_test_data=True)
        with self.assertRaises(ValueError):
            search_catalog(self.root / "absent.sqlite", "Test")
