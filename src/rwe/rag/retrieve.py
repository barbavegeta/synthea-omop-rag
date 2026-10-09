"""Patient-scoped retrieval: BM25, dense (pgvector), and hybrid (Reciprocal Rank Fusion).

Every search is restricted to one patient's chunks, as in chart search: a question about a
patient must never be answered from someone else's notes. This also means the corpus per
query is small (one chart), which the write-up states as a limitation.
"""

from __future__ import annotations

import re

import bm25s
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from rwe.config import RagConfig
from rwe.rag.embed import Embedder

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./][a-z0-9]+)*")
# Small, conservative stopword list: clinical words like "no", "not", "denies" are KEPT,
# because negation is exactly what this evaluation probes.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "with",
        "did",
        "does",
        "do",
        "any",
        "if",
        "so",
    ]
)

MODES = ("bm25", "dense", "hybrid", "hybrid_recency")


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def rrf(rankings: list[list[str]], k: int) -> list[str]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank). Uses ranks only,
    so BM25 and cosine scores on different scales never need calibrating against each other."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda d: (-scores[d], d))


def recency_rerank(ranking: list[str], dates: dict, window: int) -> list[str]:
    """Re-sort the top `window` newest-first (equal dates keep their order); keep the rest."""
    head = sorted(enumerate(ranking[:window]), key=lambda ic: (dates[ic[1]], -ic[0]), reverse=True)
    return [cid for _, cid in head] + ranking[window:]


class Retriever:
    def __init__(
        self, conn: psycopg.Connection, strategy: str, embedder: Embedder, cfg: RagConfig
    ) -> None:
        register_vector(conn)
        self.conn, self.strategy, self.embedder, self.cfg = conn, strategy, embedder, cfg
        self._bm25: dict[int, tuple[bm25s.BM25 | None, list[str]]] = {}
        self._note_dates: dict[int, dict[str, object]] = {}

    def _bm25_index(self, person_id: int):
        if person_id not in self._bm25:
            rows = self.conn.execute(
                "select chunk_id, content from rag.chunk where strategy = %s and person_id = %s"
                " order by chunk_id",
                (self.strategy, person_id),
            ).fetchall()
            ids = [cid for cid, _ in rows]
            corpus = [tokenize(content) for _, content in rows]
            index = None
            if ids:
                index = bm25s.BM25()
                index.index(corpus, show_progress=False)
            self._bm25[person_id] = (index, ids)
        return self._bm25[person_id]

    def bm25(self, person_id: int, query: str, k: int) -> list[str]:
        index, ids = self._bm25_index(person_id)
        terms = tokenize(query)
        if index is None or not terms:
            return []
        docs, scores = index.retrieve([terms], k=min(k, len(ids)), show_progress=False)
        # chunks with no term in common score 0: leave them unranked, not in arbitrary order
        return [ids[d] for d, s in zip(docs[0], scores[0], strict=True) if s > 0]

    def dense(self, person_id: int, query: str, k: int) -> list[str]:
        vector = np.asarray(self.embedder.query(query), dtype=np.float32)
        rows = self.conn.execute(
            """select chunk_id from rag.chunk
               where strategy = %s and person_id = %s and embedding is not null
               order by embedding <=> %s, chunk_id limit %s""",
            (self.strategy, person_id, vector, k),
        ).fetchall()
        return [r[0] for r in rows]

    def hybrid(self, person_id: int, query: str, k: int) -> list[str]:
        depth = self.cfg.candidate_depth
        fused = rrf(
            [self.bm25(person_id, query, depth), self.dense(person_id, query, depth)],
            self.cfg.rrf_k,
        )
        return fused[:k]

    def is_temporal(self, query: str) -> bool:
        q = query.lower()
        return any(re.search(rf"\b{re.escape(cue)}\b", q) for cue in self.cfg.temporal_cues)

    def _dates(self, person_id: int) -> dict[str, object]:
        if person_id not in self._note_dates:
            rows = self.conn.execute(
                "select chunk_id, note_date from rag.chunk where strategy = %s and person_id = %s",
                (self.strategy, person_id),
            ).fetchall()
            self._note_dates[person_id] = dict(rows)
        return self._note_dates[person_id]

    def hybrid_recency(self, person_id: int, query: str, k: int) -> list[str]:
        """Hybrid, then -- only for questions with a temporal cue -- the top `recency_window`
        re-sorted newest-first (ties keep hybrid order); the rest of the list is unchanged.
        Similarity search has no notion of time; this adds the minimum needed for
        'most recent' / 'currently' questions, whose evidence is in the latest note."""
        ranking = self.hybrid(person_id, query, self.cfg.candidate_depth)
        if not self.is_temporal(query):
            return ranking[:k]
        return recency_rerank(ranking, self._dates(person_id), self.cfg.recency_window)[:k]

    def search(self, mode: str, person_id: int, query: str, k: int) -> list[str]:
        modes = {
            "bm25": self.bm25,
            "dense": self.dense,
            "hybrid": self.hybrid,
            "hybrid_recency": self.hybrid_recency,
        }
        return modes[mode](person_id, query, k)
