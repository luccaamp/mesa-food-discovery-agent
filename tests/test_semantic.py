import json
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
    import onnxruntime
    import tokenizers
except ImportError as error:
    raise unittest.SkipTest("Install .[semantic] to run vector retrieval tests") from error

from meal_discovery.catalog import build_catalog
from meal_discovery.semantic import (SemanticSearch, build_semantic, normalize_vectors,
                                     reciprocal_rank_fusion, sample_key)
from meal_discovery.singapore import prepare_singapore
from meal_discovery.embeddings import verify_model
from test_singapore import source_fixture


class FixtureEncoder:
    description = {"repository": "synthetic-test-only", "revision": "fixture", "dimension": 384}

    def encode(self, texts, *, kind):
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        for offset, text in enumerate(texts):
            vectors[offset, 0 if "one" in text.lower() or "primeiro" in text.lower() else 1] = 1
        return vectors


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source_fixture(self.root / "raw")
        dataset = self.root / "dataset.sqlite"
        prepare_singapore(self.root / "raw", dataset, allow_test_data=True)
        self.catalog = self.root / "catalog.sqlite"
        build_catalog(dataset, self.catalog, allow_test_data=True)
        protocol = json.loads((Path(__file__).parents[1] / "configs/semantic-pilot-v1.json").read_text())
        protocol["sample_size"] = 2
        self.protocol = self.root / "protocol.json"
        self.protocol.write_text(json.dumps(protocol))
        self.index = self.root / "semantic.sqlite"
        self.manifest = build_semantic(self.catalog, self.index, self.protocol, self.root,
                                        allow_test_data=True, encoder=FixtureEncoder())
        self.search = SemanticSearch(self.index, self.root, allow_test_data=True, encoder=FixtureEncoder())

    def test_nonliteral_ranking_filters_and_provenance(self):
        result = self.search.search("primeiro", limit=1)
        self.assertEqual(result["items"][0]["product_id"], "p1")
        self.assertEqual(result["lexical_matches"], 0)
        self.assertEqual(result["eligible_products"], 2)
        self.assertEqual(self.search.search("primeiro", max_price=0)["items"], [])
        self.assertEqual(self.search.search("primeiro", min_price=2)["items"][0]["product_id"], "p2")
        self.assertEqual(self.search.search("primeiro", cuisine="missing")["items"], [])
        self.assertEqual(result["retrieval"]["indexed_products"], 2)
        self.assertFalse(result["retrieval"]["official_test_orders_used"])

    def test_comparison_uses_same_pool_and_hybrid_does_not_invent_keys(self):
        for mode in ("lexical", "semantic", "hybrid"):
            result = self.search.search("Test one", mode=mode, limit=1)
            self.assertEqual(result["items"][0]["product_id"], "p1")
            self.assertEqual(result["provenance"]["products"], 2)
        self.assertEqual(self.search.search("primeiro", mode="lexical")["items"], [])

    def test_invalid_vectors_queries_and_encoder_mismatch_fail(self):
        for vectors in (np.zeros((1, 384)), np.full((1, 384), np.nan), np.ones((1, 2))):
            with self.assertRaises(ValueError):
                normalize_vectors(vectors, 1)
        for kwargs in ({"limit": 0}, {"limit": True}, {"min_price": float("nan")}, {"mode": "unknown"}):
            with self.assertRaises(ValueError):
                self.search.search("test", **kwargs)
        changed = FixtureEncoder()
        changed.description = {**changed.description, "revision": "different"}
        with self.assertRaisesRegex(ValueError, "differs"):
            SemanticSearch(self.index, self.root, allow_test_data=True, encoder=changed)

    def test_synthetic_or_injected_encoder_cannot_enter_public_pipeline(self):
        with self.assertRaises(ValueError):
            SemanticSearch(self.index, self.root)
        with self.assertRaises(ValueError):
            build_semantic(self.catalog, self.root / "blocked.sqlite", self.protocol, self.root)
        with self.assertRaisesRegex(ValueError, "pinned E5"):
            SemanticSearch(self.index, self.root, encoder=FixtureEncoder())
        self.assertFalse((self.root / "blocked.sqlite").exists())

    def test_sample_is_deterministic_and_broken_alignment_fails(self):
        self.assertEqual(sample_key("seed", "v1", "p1"), sample_key("seed", "v1", "p1"))
        self.assertNotEqual(sample_key("seed", "v1", "p1"), sample_key("seed", "v2", "p1"))
        connection = sqlite3.connect(self.index)
        try:
            connection.execute("DELETE FROM vectors WHERE item_id=1")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ValueError, "misaligned"):
            SemanticSearch(self.index, self.root, allow_test_data=True, encoder=FixtureEncoder())

    def test_rrf_duplicate_items_do_not_inflate_scores(self):
        keys, scores = reciprocal_rank_fusion([["a", "a", "b"], ["b", "a"]])
        self.assertEqual(keys, ["a", "b"])
        self.assertAlmostEqual(scores["a"], 1 / 61 + 1 / 62)
        self.assertAlmostEqual(scores["b"], scores["a"])

    def test_model_verification_rejects_missing_and_changed_files(self):
        with self.assertRaises(ValueError):
            verify_model(self.root / "absent-model")
        content = b"test-only-file"
        path = self.root / "fixture.bin"
        path.write_bytes(content)
        pins = {"fixture.bin": {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}}
        with patch("meal_discovery.embeddings.MODEL_FILES", pins):
            verify_model(self.root)
            path.write_bytes(b"x" * len(content))
            with self.assertRaises(ValueError):
                verify_model(self.root)

    def test_development_metrics_and_unjudged_review_are_distinct(self):
        from scripts.evaluate_retrieval import evaluate
        from scripts.prepare_relevance_review import prepare

        config = json.loads((Path(__file__).parents[1] / "configs/retrieval-development-v1.json").read_text(encoding="utf-8"))
        config["queries"] = [{"id": "fixture", "language": "pt", "query": "primeiro", "name_patterns": ["one"]}]
        protocol = self.root / "evaluation.json"
        protocol.write_text(json.dumps(config), encoding="utf-8")
        with patch("scripts.evaluate_retrieval.SemanticSearch", return_value=self.search):
            result = evaluate(self.index, self.root, protocol)
        self.assertEqual(result["kind"], "development_silver_labels_not_human_relevance")
        self.assertEqual(result["summary"]["lexical"]["pt"]["ndcg"], 0)
        self.assertEqual(result["summary"]["semantic"]["pt"]["ndcg"], 1)
        with patch("scripts.prepare_relevance_review.SemanticSearch", return_value=self.search):
            review = prepare(self.index, self.root, protocol)
        self.assertEqual(review["status"], "pending_human_review")
        self.assertIsNone(review["reviewer"])
        self.assertTrue(review["cases"][0]["candidates"])
        self.assertTrue(all(row["relevance"] is None for row in review["cases"][0]["candidates"]))
