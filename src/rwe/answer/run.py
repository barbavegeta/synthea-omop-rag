"""Run the answering step over a set of questions: retrieve, ask, grade, store (ADR-0013).

Retrieval runs first, sequentially (it shares one DB connection and the embedding model);
the LLM calls then run on a small thread pool through the budget-checked client. A
dry run builds every request and prices it without sending anything.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from rwe.answer import grade, prompt
from rwe.config import PipelineConfig
from rwe.llm.client import BudgetExceededError, LlmClient, LlmRequest
from rwe.rag.retrieve import Retriever

# For the dry-run *expected* cost only (the cap reserves max_tokens). Pilot measured 125-143
# output tokens per answer across both models and both efforts; 200 keeps a margin.
ASSUMED_OUTPUT_TOKENS = 200


def stratified_sample(questions: list[dict], per_template: int, seed: int) -> list[dict]:
    by_template: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        by_template[q["template"]].append(q)
    rng = random.Random(f"{seed}:pilot-sample")
    out = []
    for template in sorted(by_template):
        pool = sorted(by_template[template], key=lambda q: q["question_id"])
        out += rng.sample(pool, k=min(per_template, len(pool)))
    return sorted(out, key=lambda q: q["question_id"])


def build_requests(
    conn: psycopg.Connection,
    retriever: Retriever,
    cfg: PipelineConfig,
    questions: list[dict],
    model: str,
    effort: str,
    mode: str,
    run_name: str,
) -> list[tuple[dict, list[str], LlmRequest]]:
    out = []
    for q in questions:
        chunk_ids = retriever.search(mode, q["person_id"], q["question"], cfg.llm.top_k)
        contents = dict(
            conn.execute(
                "select chunk_id, content from rag.chunk where chunk_id = any(%s)", (chunk_ids,)
            ).fetchall()
        )
        chunks = [contents[c] for c in chunk_ids]
        if not chunks:  # every eval patient has notes, so this is a retrieval bug: fail loudly
            raise RuntimeError(f"{mode} retrieved nothing for {q['question_id']}")
        req = LlmRequest(
            model=model,
            system=prompt.SYSTEM,
            user=prompt.user_message(q["question"], q["as_of"], chunks),
            schema=prompt.schema(len(chunks)),
            effort=effort,
            max_tokens=cfg.llm.max_tokens,
            purpose=f"answer:{run_name}",
        )
        out.append((q, chunk_ids, req))
    return out


def estimate(client: LlmClient, planned: list[tuple[dict, list[str], LlmRequest]]) -> dict:
    todo = [req for _, _, req in planned if client.cached(req) is None]
    in_tokens = sum(r.estimated_input_tokens() for r in todo)
    if not todo:
        return {"calls": 0, "cached": len(planned), "expected_usd": 0.0, "worst_case_usd": 0.0}
    price_in, price_out = client.cfg.price(todo[0].model)
    expected = (in_tokens * price_in + len(todo) * ASSUMED_OUTPUT_TOKENS * price_out) / 1e6
    worst = sum(client.reservation(r) for r in todo)
    return {
        "calls": len(todo),
        "cached": len(planned) - len(todo),
        "est_input_tokens": in_tokens,
        "expected_usd": round(expected, 4),
        "worst_case_usd": round(worst, 4),
        "spent_so_far_usd": round(client.spent, 4),
        "budget_usd": client.cfg.budget_usd,
    }


def execute(
    conn: psycopg.Connection,
    client: LlmClient,
    planned: list[tuple[dict, list[str], LlmRequest]],
    run_name: str,
    mode: str,
    workers: int,
    log=print,
) -> pd.DataFrame:
    results: dict[str, object] = {}
    stopped = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.complete, req): q["question_id"] for q, _, req in planned}
        for done, fut in enumerate(as_completed(futures), start=1):
            qid = futures[fut]
            try:
                results[qid] = fut.result()
            except BudgetExceededError as exc:
                stopped = stopped or str(exc)
                results[qid] = None
            if done % 20 == 0 or done == len(futures):
                log(f"  {done}/{len(futures)} answered; spent ${client.spent:.4f}")
    if stopped:
        log(f"STOPPED BY BUDGET CAP: {stopped}")

    rows = []
    with conn.transaction():
        for q, chunk_ids, req in planned:
            res = results.get(q["question_id"])
            parsed = res.parsed if res else None
            correct, detail = grade.grade(q, parsed) if res else (False, {"error": "not run"})
            conn.execute(
                """insert into eval.answer (run_name, question_id, model, effort, retrieval_mode,
                       shown_chunks, response, stop_reason, cache_key, correct, grade_detail)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (run_name, question_id) do update set
                       model = excluded.model, effort = excluded.effort,
                       retrieval_mode = excluded.retrieval_mode,
                       shown_chunks = excluded.shown_chunks, response = excluded.response,
                       stop_reason = excluded.stop_reason, cache_key = excluded.cache_key,
                       correct = excluded.correct, grade_detail = excluded.grade_detail""",
                (
                    run_name,
                    q["question_id"],
                    req.model,
                    req.effort,
                    mode,
                    chunk_ids,
                    Jsonb(parsed) if parsed is not None else None,
                    res.stop_reason if res else None,
                    res.cache_key if res else None,
                    correct,
                    Jsonb(detail),
                ),
            )
            rows.append(
                {
                    "question_id": q["question_id"],
                    "template": q["template"],
                    "phenomenon": q["phenomenon"],
                    "correct": correct,
                    "cost_usd": res.cost_usd if res else 0.0,
                    "cached": res.cached if res else False,
                    "stop_reason": res.stop_reason if res else "not_run",
                }
            )
    return pd.DataFrame(rows)


def record_from_cache(
    conn: psycopg.Connection,
    client: LlmClient,
    planned: list[tuple[dict, list[str], LlmRequest]],
    run_name: str,
    mode: str,
) -> pd.DataFrame:
    """Grade and store a run whose responses are already in the cache (e.g. a collected
    batch). Requests with no cached response are stored as not run, never silently dropped."""
    rows = []
    with conn.transaction():
        for q, chunk_ids, req in planned:
            hit = client.cached(req)
            parsed = json.loads(hit["text"]) if hit else None
            correct, detail = grade.grade(q, parsed) if hit else (False, {"error": "not run"})
            conn.execute(
                """insert into eval.answer (run_name, question_id, model, effort, retrieval_mode,
                       shown_chunks, response, stop_reason, cache_key, correct, grade_detail)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (run_name, question_id) do update set
                       model = excluded.model, effort = excluded.effort,
                       retrieval_mode = excluded.retrieval_mode,
                       shown_chunks = excluded.shown_chunks, response = excluded.response,
                       stop_reason = excluded.stop_reason, cache_key = excluded.cache_key,
                       correct = excluded.correct, grade_detail = excluded.grade_detail""",
                (
                    run_name,
                    q["question_id"],
                    req.model,
                    req.effort,
                    mode,
                    chunk_ids,
                    Jsonb(parsed) if parsed is not None else None,
                    hit["stop_reason"] if hit else "not_run",
                    req.cache_key(client.provider.name),
                    correct,
                    Jsonb(detail),
                ),
            )
            rows.append(
                {
                    "question_id": q["question_id"],
                    "template": q["template"],
                    "correct": correct,
                    "answered": hit is not None,
                }
            )
    return pd.DataFrame(rows)
