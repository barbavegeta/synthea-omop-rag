"""Embedders: the local bge-small model, and a deterministic fake for CI.

Both return L2-normalised float32 vectors, so cosine similarity = dot product and
pgvector's cosine distance (<=>) ranks identically to inner product.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Protocol

import numpy as np

from rwe.config import REPO_ROOT, RagConfig

MODEL_CACHE = REPO_ROOT / "data" / "models"
TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str

    def passages(self, texts: list[str]) -> np.ndarray: ...
    def query(self, text: str) -> np.ndarray: ...


class BgeEmbedder:
    """BAAI/bge-small-en-v1.5 via sentence-transformers, on CPU, pinned to a commit.
    bge v1.5 is trained with an instruction prefix on queries (not on passages)."""

    def __init__(self, cfg: RagConfig) -> None:
        # Once the pinned commit is cached, run offline: no Hub calls, nothing can change.
        snapshot = (
            MODEL_CACHE
            / f"models--{cfg.model_name.replace('/', '--')}"
            / "snapshots"
            / cfg.model_revision
        )
        if snapshot.is_dir():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer  # optional 'embed' extra

        self.name = f"{cfg.model_name}@{cfg.model_revision[:12]}"
        self.instruction = cfg.query_instruction
        self.batch_size = cfg.batch_size
        self.model = SentenceTransformer(
            cfg.model_name,
            revision=cfg.model_revision,
            device="cpu",
            cache_folder=str(MODEL_CACHE),
        )

    def passages(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)

    def query(self, text: str) -> np.ndarray:
        return self.passages([self.instruction + text])[0]


class FakeEmbedder:
    """Feature hashing of word tokens into `dim` buckets: deterministic, no download,
    and lexically meaningful enough for the CI pipeline to exercise every code path.
    Its retrieval quality is not reported anywhere."""

    def __init__(self, cfg: RagConfig) -> None:
        self.name = f"fake-hashing-{cfg.dim}"
        self.dim = cfg.dim

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in TOKEN_RE.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._one(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def query(self, text: str) -> np.ndarray:
        return self._one(text)


def make_embedder(cfg: RagConfig) -> Embedder:
    return BgeEmbedder(cfg) if cfg.embedder == "bge" else FakeEmbedder(cfg)
