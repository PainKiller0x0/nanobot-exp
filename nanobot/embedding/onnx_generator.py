"""
ONNX-based embedding generator — NO torch at runtime.
Uses onnxruntime (CPU) + tokenizers (Rust, no torch).

One-time setup (first deploy, or after model change):
    python3 -c "from nanobot.embedding import ONNXEmbeddingGenerator; ONNXEmbeddingGenerator.prepare()"

Runtime usage (same interface as EmbeddingGenerator):
    from nanobot.embedding import ONNXEmbeddingGenerator
    gen = ONNXEmbeddingGenerator()
    emb = gen.encode("hello world")          # -> np.ndarray (384,) float16
    embs = gen.encode(["hello", "world"])   # -> np.ndarray (2, 384) float16
    sim = gen.cosine_similarity(emb1, emb2)  # -> float
"""

from __future__ import annotations

import hashlib
import pickle
import threading
from pathlib import Path
from typing import Union, List

import numpy as np

_DEFAULT_MODEL_DIR = Path.home() / ".nanobot" / "onnx_embedding"
_NANOBOT_DATA      = Path("/root/nanobot/nanobot/data")
_EXISTING_TOKENIZER = _NANOBOT_DATA / "embedding_tokenizer"
_EXISTING_ONNX      = _NANOBOT_DATA / "embedding_model.onnx"


class ONNXEmbeddingGenerator:
    """
    Drop-in replacement for EmbeddingGenerator.
    Memory: ~167 MB RSS (vs ~811 MB with torch).
    Zero torch imports at runtime.
    """

    EMBEDDING_DIM = 384
    MAX_SEQ_LEN   = 384

    def __init__(
        self,
        model_dir: Path = None,
        cache_dir: Path = None,
    ):
        if model_dir:
            self.model_dir = Path(model_dir)
        elif _EXISTING_TOKENIZER.exists() and _EXISTING_ONNX.exists():
            self.model_dir = _NANOBOT_DATA
        else:
            self.model_dir = _DEFAULT_MODEL_DIR

        self.cache_dir = Path(cache_dir or self.model_dir / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._tok  = None
        self._sess = None
        self._lock = threading.Lock()

    def _ensure_ready(self):
        if self._tok is not None and self._sess is not None:
            return
        with self._lock:
            if self._tok is not None and self._sess is not None:
                return
            self._init_once()

    def _init_once(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        tok_path = self.model_dir / "embedding_tokenizer" / "tokenizer.json"
        onnx_path = self.model_dir / "embedding_model.onnx"

        if not tok_path.exists() or not onnx_path.exists():
            raise FileNotFoundError(
                f"ONNX model/tokenizer not found.\n"
                f"  tok: {tok_path}\n"
                f"  onnx: {onnx_path}\n"
                "Run: python3 -c 'from nanobot.embedding import ONNXEmbeddingGenerator; "
                "ONNXEmbeddingGenerator.prepare()'"
            )

        self._tok = Tokenizer.from_file(str(tok_path))
        self._tok.enable_truncation(max_length=self.MAX_SEQ_LEN)
        self._tok.enable_padding(
            pad_id=0, pad_token="[PAD]", length=self.MAX_SEQ_LEN
        )

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_mem_pattern = False
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self._sess = ort.InferenceSession(
            str(onnx_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

    @staticmethod
    def _mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
        mask_f = mask.astype(np.float32)
        masked = hidden * np.expand_dims(mask_f, axis=-1)
        return masked.sum(axis=1) / (mask_f.sum(axis=1, keepdims=True) + 1e-9)

    def encode(
        self,
        text: Union[str, List[str]],
        use_cache: bool = True,
        compress: bool = True,
    ) -> np.ndarray:
        self._ensure_ready()

        is_single = isinstance(text, str)
        texts = [text] if is_single else list(text)

        cached: dict[int, np.ndarray] = {}
        pending: list[tuple[int, str]] = []

        if use_cache:
            for i, t in enumerate(texts):
                key = hashlib.md5(t.encode()).hexdigest()
                path = self.cache_dir / f"{key}.pkl"
                if path.exists():
                    with open(path, "rb") as f:
                        cached[i] = pickle.load(f)
                else:
                    pending.append((i, t))

        if pending:
            indices, strs = zip(*pending)
            encodings = self._tok.encode_batch(list(strs))

            ids_arr  = np.array([e.ids for e in encodings], dtype=np.int64)
            mask_arr = np.array([e.attention_mask for e in encodings], dtype=np.int64)

            (hidden,) = self._sess.run(
                ["last_hidden_state"],
                {"input_ids": ids_arr, "attention_mask": mask_arr},
            )

            pooled = self._mean_pool(hidden, mask_arr)

            if compress:
                pooled = pooled.astype(np.float16)

            for idx, text_str, emb in zip(indices, strs, pooled):
                if use_cache:
                    key = hashlib.md5(text_str.encode()).hexdigest()
                    path = self.cache_dir / f"{key}.pkl"
                    with open(path, "wb") as f:
                        pickle.dump(emb, f)
                cached[idx] = emb

        result = np.array([cached[i] for i in range(len(texts))], dtype=np.float16)
        return result[0] if is_single else result

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        a = a.astype(np.float32) if a.dtype == np.float16 else a
        b = b.astype(np.float32) if b.dtype == np.float16 else b
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    @classmethod
    def prepare(cls, model_dir: Path = None) -> "ONNXEmbeddingGenerator":
        import torch
        from transformers import AutoTokenizer, AutoModel

        model_dir = Path(model_dir or _DEFAULT_MODEL_DIR)
        onnx_path = model_dir / "embedding_model.onnx"
        tok_dir   = model_dir / "embedding_tokenizer"

        if onnx_path.exists() and tok_dir.exists():
            print(f"[ONNX] Already prepared at {model_dir}")
            return cls(model_dir=model_dir)

        import os
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        print(f"[ONNX] Downloading sentence-transformers/all-MiniLM-L6-v2 ...")
        tok = AutoTokenizer.from_pretrained(
            "sentence-transformers/all-MiniLM-L6-v2"
        )
        m = AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
        m.eval()

        tok_dir.mkdir(parents=True, exist_ok=True)
        tok.save_pretrained(str(tok_dir))
        print(f"[ONNX] Tokenizer -> {tok_dir}")

        dummy = tok(
            ["x"], padding=True, truncation=True,
            max_length=cls.MAX_SEQ_LEN, return_tensors="pt"
        )
        torch.onnx.export(
            m,
            (dummy["input_ids"], dummy["attention_mask"]),
            str(onnx_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes={
                "input_ids":         {0: "batch_size", 1: "seq_len"},
                "attention_mask":    {0: "batch_size", 1: "seq_len"},
                "last_hidden_state": {0: "batch_size", 1: "seq_len"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
        print(f"[ONNX] Model -> {onnx_path}")
        del m
        return cls(model_dir=model_dir)
