"""Pinned local multilingual E5 inference, with no remote code execution."""

from pathlib import Path

from .dataset import file_hash

MODEL_REPOSITORY = "Xenova/multilingual-e5-small"
MODEL_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
MODEL_FILES = {
    "onnx/model_quantized.onnx": {"bytes": 118308185, "sha256": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193"},
    "tokenizer.json": {"bytes": 17082730, "sha256": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"},
}


def verify_model(directory: Path):
    for name, expected in MODEL_FILES.items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != expected["bytes"] or file_hash(path) != expected["sha256"]:
            raise ValueError("Missing or changed pinned E5 files; run scripts/fetch_embedding_model.py")


class E5Encoder:
    def __init__(self, directory: Path, *, threads=4):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        verify_model(directory)
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(directory / "onnx/model_quantized.onnx"),
                                           sess_options=options, providers=["CPUExecutionProvider"])
        self.input_names = {item.name for item in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"} <= self.input_names <= {"input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("Unexpected model inputs")
        self.description = {"base_model": "intfloat/multilingual-e5-small", "repository": MODEL_REPOSITORY,
                            "revision": MODEL_REVISION, "files": MODEL_FILES, "dimension": 384,
                            "runtime": "onnxruntime CPU", "quantization": "ONNX dynamic int8",
                            "max_tokens": 128, "pooling": "attention-masked mean then L2 normalization",
                            "prefixes": {"query": "query: ", "passage": "passage: "},
                            "threads": threads, "license": "MIT (base model)"}

    def encode(self, texts, *, kind):
        import numpy as np

        if kind not in {"query", "passage"} or not texts:
            raise ValueError("Expected nonempty texts and an E5 query/passage role")
        encodings = self.tokenizer.encode_batch([kind + ": " + text for text in texts])
        inputs = {"input_ids": np.asarray([row.ids for row in encodings], dtype=np.int64),
                  "attention_mask": np.asarray([row.attention_mask for row in encodings], dtype=np.int64),
                  "token_type_ids": np.asarray([row.type_ids for row in encodings], dtype=np.int64)}
        hidden = self.session.run(["last_hidden_state"], {key: inputs[key] for key in self.input_names})[0]
        mask = inputs["attention_mask"][..., None]
        pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
        normalized = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        return normalized.astype(np.float32)
