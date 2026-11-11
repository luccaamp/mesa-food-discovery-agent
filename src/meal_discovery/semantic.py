"""Experimental semantic/hybrid retrieval on a frozen real-catalog subset."""

import hashlib
import json
import os
from .file_publish import publish_new
from pathlib import Path
import sqlite3
import tempfile

import numpy as np

from .catalog import open_catalog, search_catalog
from .dataset import file_hash
from .embeddings import E5Encoder, MODEL_REPOSITORY, MODEL_REVISION


def read_protocol(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    if (config.get("protocol_version") != "semantic-pilot-v1" or config.get("dimension") != 384
            or config.get("model_repository") != MODEL_REPOSITORY or config.get("model_revision") != MODEL_REVISION
            or not isinstance(config.get("sample_seed"), str) or not config["sample_seed"]
            or config.get("document_template") != "{name}. Cuisine: {primary_cuisine}."
            or type(config.get("sample_size")) is not int or config["sample_size"] < 1
            or type(config.get("batch_size")) is not int or not 1 <= config["batch_size"] <= 256
            or config.get("hybrid") != {"method": "reciprocal_rank_fusion", "rank_constant": 60, "candidate_depth": 50}):
        raise ValueError("Unsupported semantic protocol")
    return config


def sample_key(seed, vendor, product):
    value = json.dumps([seed, vendor, product], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_vectors(vectors, rows, dimension=384):
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (rows, dimension) or not np.isfinite(matrix).all():
        raise ValueError("Invalid embedding shape or nonfinite values")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms <= 1e-8):
        raise ValueError("Zero-length embedding")
    return matrix / norms


def build_semantic(index: Path, output: Path, protocol: Path, model_dir: Path,
                   *, allow_test_data=False, encoder=None, progress=None):
    if output.exists() or output.suffix != ".sqlite":
        raise ValueError("Choose a new .sqlite semantic index path")
    if encoder is not None and not allow_test_data:
        raise ValueError("Production indexing must use the pinned E5 encoder")
    config_hash = file_hash(protocol)
    config = read_protocol(protocol)
    source, provenance = open_catalog(index, allow_test_data=allow_test_data)
    target = None
    temporary = None
    emit = progress or (lambda message: None)
    try:
        source_hash = file_hash(index)
        source.create_function("sample_key", 2, lambda vendor, product: sample_key(config["sample_seed"], vendor, product), deterministic=True)
        rows = source.execute("""SELECT vendor_id,product_id,name,unit_price,primary_cuisine FROM items
                                 ORDER BY sample_key(vendor_id,product_id),vendor_id,product_id LIMIT ?""",
                              (config["sample_size"],)).fetchall()
        if len(rows) != config["sample_size"]:
            raise ValueError("Source catalog is smaller than the frozen sample size")
        encoder = encoder or E5Encoder(model_dir)
        output.parent.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix="semantic-", suffix=".tmp", dir=output.parent)
        os.close(handle)
        temporary = Path(filename)
        target = sqlite3.connect(temporary)
        target.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE items(id INTEGER PRIMARY KEY,vendor_id TEXT NOT NULL,product_id TEXT NOT NULL,
                name TEXT NOT NULL,unit_price REAL,primary_cuisine TEXT NOT NULL,UNIQUE(vendor_id,product_id));
            CREATE INDEX items_cuisine_price ON items(primary_cuisine,unit_price);
            CREATE VIRTUAL TABLE item_search USING fts5(name,primary_cuisine,content='items',content_rowid='id',
                tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE vectors(item_id INTEGER PRIMARY KEY, embedding BLOB NOT NULL);
        """)
        with target:
            target.executemany("INSERT INTO items(vendor_id,product_id,name,unit_price,primary_cuisine) VALUES (?,?,?,?,?)", rows)
            target.execute("INSERT INTO item_search(item_search) VALUES ('rebuild')")
            for start in range(0, len(rows), config["batch_size"]):
                batch = rows[start:start + config["batch_size"]]
                texts = [config["document_template"].format(**dict(row)) for row in batch]
                vectors = normalize_vectors(encoder.encode(texts, kind="passage"), len(batch))
                target.executemany("INSERT INTO vectors VALUES (?,?)", [(start + offset + 1, vector.astype('<f4').tobytes())
                                                                         for offset, vector in enumerate(vectors)])
                if (start // config["batch_size"]) % 25 == 0 or start + len(batch) == len(rows):
                    emit(f"Embedded {start + len(batch):,}/{len(rows):,} real products")
            subset = {**provenance, "products": len(rows),
                      "cuisines": len({row["primary_cuisine"] for row in rows}),
                      "limitations": provenance["limitations"] + ["Experimental semantic pilot subset, not the full catalog."]}
            manifest = {"schema_version": 1, "index_version": "semantic-pilot-v1", "data_kind": provenance["data_kind"],
                        "source_catalog_sha256": source_hash, "source_catalog_products": provenance["products"],
                        "indexed_products": len(rows), "catalog_fraction": len(rows) / provenance["products"],
                        "sample_keys_sha256": hashlib.sha256("\n".join(json.dumps([row['vendor_id'],row['product_id']],separators=(',',':')) for row in rows).encode()).hexdigest(),
                        "protocol_sha256": config_hash, "protocol": config, "model": encoder.description,
                        "official_test_orders_used": False}
            if file_hash(index) != source_hash or file_hash(protocol) != config_hash:
                raise ValueError("Source or protocol changed during indexing")
            target.executemany("INSERT INTO metadata VALUES (?,?)", [("catalog_manifest", json.dumps(subset)),
                                                                      ("semantic_manifest", json.dumps(manifest))])
        target.close()
        publish_new(temporary, output)
        return manifest
    finally:
        source.close()
        if target:
            target.close()
        if temporary:
            temporary.unlink(missing_ok=True)


def reciprocal_rank_fusion(rankings, *, constant=60):
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(dict.fromkeys(ranking), 1):
            scores[item] = scores.get(item, 0.0) + 1 / (constant + rank)
    return sorted(scores, key=lambda item: (-scores[item], item)), scores


class SemanticSearch:
    def __init__(self, index: Path, model_dir: Path, *, allow_test_data=False, encoder=None):
        if encoder is not None and not allow_test_data:
            raise ValueError("Production search must use the pinned E5 encoder")
        connection, self.provenance = open_catalog(index, allow_test_data=allow_test_data)
        try:
            row = connection.execute("SELECT value FROM metadata WHERE key='semantic_manifest'").fetchone()
            self.manifest = json.loads(row[0]) if row else {}
            if self.manifest.get("index_version") != "semantic-pilot-v1":
                raise ValueError("Unsupported semantic index")
            self.rows = [dict(row) for row in connection.execute("SELECT * FROM items ORDER BY id")]
            if (len(self.rows) != self.manifest.get("indexed_products")
                    or len(self.rows) != self.provenance.get("products")
                    or self.manifest.get("data_kind") != self.provenance.get("data_kind")):
                raise ValueError("Semantic corpus metadata differs from its contents")
            stored = connection.execute("SELECT item_id,embedding FROM vectors ORDER BY item_id").fetchall()
            if [row["id"] for row in self.rows] != [row["item_id"] for row in stored] or not stored:
                raise ValueError("Missing or misaligned semantic vectors")
            self.vectors = normalize_vectors(np.stack([np.frombuffer(row["embedding"], dtype='<f4') for row in stored]), len(stored))
        finally:
            connection.close()
        self.encoder = encoder or E5Encoder(model_dir)
        for key in ("repository", "revision", "files", "dimension", "max_tokens", "pooling", "prefixes"):
            if self.manifest["model"].get(key) != self.encoder.description.get(key):
                raise ValueError("Query encoder differs from the indexed document encoder")
        self.index = index
        self.allow_test_data = allow_test_data
        self.by_key = {(row["vendor_id"], row["product_id"]): row for row in self.rows}

    def search(self, query, *, mode="semantic", cuisine=None, min_price=None, max_price=None, limit=10):
        if mode not in {"lexical", "semantic", "hybrid"}:
            raise ValueError("Unsupported retrieval mode")
        # Shared literal-query, price and limit validation; BM25 runs on the same subset.
        lexical = search_catalog(self.index, query, cuisine=cuisine, min_price=min_price, max_price=max_price,
                                 limit=50 if mode == "hybrid" else limit, allow_test_data=self.allow_test_data)
        if mode == "hybrid" and (type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError("Limit must be between 1 and 50")
        eligible = [offset for offset, row in enumerate(self.rows)
                    if (cuisine is None or row["primary_cuisine"] == cuisine)
                    and (min_price is None or row["unit_price"] is not None and row["unit_price"] >= min_price)
                    and (max_price is None or row["unit_price"] is not None and row["unit_price"] <= max_price)]
        scores = {}
        if mode == "lexical":
            keys = [(row["vendor_id"], row["product_id"]) for row in lexical["items"]]
            scores = {key: -row["lexical_score"] for key, row in zip(keys, lexical["items"])}
        elif eligible:
            vector = normalize_vectors(self.encoder.encode([query], kind="query"), 1)[0]
            similarities = self.vectors[eligible] @ vector
            ordered = sorted(range(len(eligible)), key=lambda offset: (-float(similarities[offset]),
                             self.rows[eligible[offset]]["vendor_id"], self.rows[eligible[offset]]["product_id"]))
            depth = 50 if mode == "hybrid" else limit
            keys = [(self.rows[eligible[offset]]["vendor_id"], self.rows[eligible[offset]]["product_id"]) for offset in ordered[:depth]]
            scores = {key: float(similarities[offset]) for key, offset in zip(keys, ordered[:depth])}
            if mode == "hybrid":
                lexical_keys = [(row["vendor_id"], row["product_id"]) for row in lexical["items"]]
                keys, scores = reciprocal_rank_fusion([keys, lexical_keys])
        else:
            keys = []
        return {"query": query, "mode": mode,
                "items": [{**{key: value for key, value in self.by_key[item].items() if key != "id"},
                           "retrieval_score": scores[item]} for item in keys[:limit]],
                "eligible_products": len(eligible), "lexical_matches": lexical["total_matches"],
                "filters": {"cuisine": cuisine, "min_price": min_price, "max_price": max_price},
                "provenance": self.provenance, "retrieval": self.manifest,
                "score_note": "Cosine or reciprocal-rank score, never a probability or proof of dietary suitability."}
