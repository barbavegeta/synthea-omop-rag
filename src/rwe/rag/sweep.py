"""Dev-only sweep of the hybrid_recency window (ADR-0012). The grid is pre-declared."""

from __future__ import annotations

import pandas as pd

from rwe import db
from rwe.config import PipelineConfig
from rwe.rag import embed, evaluate
from rwe.rag.retrieve import Retriever

GRID = (5, 10, 20)


def recency_window_sweep(cfg: PipelineConfig, strategy: str) -> pd.DataFrame:
    rows = []
    with db.connect(dbname=cfg.database) as conn:
        questions = [q for q in evaluate.load_questions(conn, "dev") if q["gold_fact_ids"]]
        relevant = evaluate.relevant_chunks(conn, strategy, questions)
        embedder = embed.make_embedder(cfg.rag)
        for n in GRID:
            rag = cfg.rag.model_copy(update={"recency_window": n})
            retriever = Retriever(conn, strategy, embedder, rag)
            for q in questions:
                ranking = retriever.search(
                    "hybrid_recency", q["person_id"], q["question"], rag.candidate_depth
                )
                rows.append(
                    {
                        "recency_window": n,
                        "template": q["template"],
                        "temporal": retriever.is_temporal(q["question"]),
                        "rank": evaluate.first_relevant_rank(ranking, relevant[q["question_id"]]),
                    }
                )
    return pd.DataFrame(rows)
