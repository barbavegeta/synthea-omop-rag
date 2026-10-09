"""Retrieval metrics against exact relevance labels (ADR-0012).

Relevant chunk: contains (whole span) at least one of the question's gold supporting facts.
Evidence is often redundant (a diagnosis date is repeated in every later note's history),
and any one relevant chunk is sufficient, so:
  recall@k  share of questions with at least one relevant chunk in the top k
  MRR       mean of 1 / rank of the first relevant chunk (0 if none within candidate_depth)
Questions with no gold facts (abstention: "not documented") are excluded; whether the
system *abstains* correctly is an answer-level metric (Phase 7).

Guard: only the dev split may be evaluated here. The test split is scored once, in Phase 7.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
import psycopg

from rwe.config import RagConfig
from rwe.rag.retrieve import MODES, Retriever


class TestSetGuardError(RuntimeError):
    """Raised when something tries to score the test split before the final run."""


def load_questions(conn: psycopg.Connection, split: str, final: bool = False) -> list[dict]:
    if split == "test" and not final:
        raise TestSetGuardError("The test split is scored once, in the final evaluation (Phase 7).")
    rows = conn.execute(
        """select question_id, person_id, template, phenomenon, question, gold_fact_ids,
                  answer, as_of::text, sql_answerable, params
           from eval.question where split = %s order by question_id""",
        (split,),
    ).fetchall()
    keys = (
        "question_id",
        "person_id",
        "template",
        "phenomenon",
        "question",
        "gold_fact_ids",
        "answer",
        "as_of",
        "sql_answerable",
        "params",
    )
    return [dict(zip(keys, r, strict=True)) for r in rows]


def relevant_chunks(conn: psycopg.Connection, strategy: str, questions: list[dict]) -> dict:
    fact_to_chunks: dict[str, set[str]] = defaultdict(set)
    for chunk_id, fact_id in conn.execute(
        """select cf.chunk_id, cf.fact_id from rag.chunk_fact cf
           join rag.chunk c using (chunk_id) where c.strategy = %s""",
        (strategy,),
    ).fetchall():
        fact_to_chunks[fact_id].add(chunk_id)
    return {
        q["question_id"]: set().union(*(fact_to_chunks[f] for f in q["gold_fact_ids"]))
        if q["gold_fact_ids"]
        else set()
        for q in questions
    }


def first_relevant_rank(ranking: list[str], relevant: set[str]) -> int | None:
    return next((i for i, cid in enumerate(ranking, start=1) if cid in relevant), None)


def evaluate(
    conn: psycopg.Connection, retriever_for, strategy: str, questions: list[dict], cfg: RagConfig
) -> pd.DataFrame:
    """One row per (question, mode) with the rank of the first relevant chunk."""
    relevant = relevant_chunks(conn, strategy, questions)
    rows = []
    retriever: Retriever = retriever_for(strategy)
    for q in questions:
        if not q["gold_fact_ids"]:
            continue  # abstention questions: nothing to retrieve
        rel = relevant[q["question_id"]]
        for mode in MODES:
            ranking = retriever.search(mode, q["person_id"], q["question"], cfg.candidate_depth)
            rows.append(
                {
                    "strategy": strategy,
                    "mode": mode,
                    "question_id": q["question_id"],
                    "template": q["template"],
                    "phenomenon": q["phenomenon"],
                    "n_relevant": len(rel),
                    "rank": first_relevant_rank(ranking, rel),
                }
            )
    return pd.DataFrame(rows)


def summarise(per_question: pd.DataFrame, k_values: list[int], by: list[str]) -> pd.DataFrame:
    def agg(g: pd.DataFrame) -> pd.Series:
        ranks = g["rank"]
        out = {"questions": len(g)}
        for k in k_values:
            out[f"recall@{k}"] = round(float((ranks.notna() & (ranks <= k)).mean()), 3)
        out["MRR"] = round(float((1.0 / ranks).fillna(0.0).mean()), 3)
        return pd.Series(out)

    return per_question.groupby(by).apply(agg, include_groups=False).reset_index()
