"""Run the note rewrite: build requests, send them (direct or batch), validate, store.

Requests are rebuilt deterministically from the notes, so processing simply looks each
one up in the response cache: direct calls and collected batches both land there. An
interrupted run can always be resumed: collect again, then process again.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor

import psycopg

from rwe.config import PipelineConfig
from rwe.llm.client import LlmClient, LlmRequest
from rwe.notes import rewrite

MAX_TOKENS = 2000  # a rewritten note is ~300-900 tokens; this is also the worst-case reservation
DEV_SAMPLE_PATIENTS = 5


def scope_patients(conn: psycopg.Connection, scope: str, seed: int) -> list[int]:
    if scope == "test":
        rows = conn.execute("select person_id from eval.eval_patient where split = 'test'")
        return sorted(r[0] for r in rows.fetchall())
    if scope == "dev-sample":
        dev = sorted(
            r[0]
            for r in conn.execute(
                "select person_id from eval.eval_patient where split = 'dev'"
            ).fetchall()
        )
        return sorted(
            random.Random(f"{seed}:rewrite-dev-sample").sample(
                dev, k=min(DEV_SAMPLE_PATIENTS, len(dev))
            )
        )
    raise ValueError(f"unknown scope {scope!r}")


def load(conn: psycopg.Connection, patients: list[int]):
    notes = conn.execute(
        """select note_id, note_text from notes.generated_note
           where person_id = any(%s) order by note_id""",
        (patients,),
    ).fetchall()
    facts: dict[int, list[rewrite.FactSpan]] = {}
    for note_id, fact_id, s, e, pol, tmp, exp in conn.execute(
        """select note_id, fact_id, span_start, span_end, polarity, temporality, experiencer
           from eval.note_fact where person_id = any(%s)""",
        (patients,),
    ).fetchall():
        index = int(fact_id.rsplit("-f", 1)[1])
        facts.setdefault(note_id, []).append(rewrite.FactSpan(index, s, e, pol, tmp, exp))
    return notes, facts


def build(cfg: PipelineConfig, notes, facts, label: str) -> list[tuple[int, str, str, LlmRequest]]:
    out = []
    for note_id, text in notes:
        tagged = rewrite.tag_note(text, facts.get(note_id, []))
        req = LlmRequest(
            model=cfg.llm.rewrite_model,
            system=rewrite.SYSTEM,
            user=f"Rewrite this note:\n\n{tagged}",
            schema=rewrite.output_schema(),
            effort=cfg.llm.effort,
            max_tokens=MAX_TOKENS,
            purpose=f"rewrite:{label}",
        )
        out.append((note_id, text, tagged, req))
    return out


def send_direct(client: LlmClient, planned, workers: int = 6) -> None:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda p: client.complete(p[3]), planned))


def process(conn: psycopg.Connection, client: LlmClient, planned, facts) -> dict:
    counts = {"ok": 0, "rejected": 0, "failed": 0}
    reasons: dict[str, int] = {}
    with conn.transaction():
        note_ids = [p[0] for p in planned]
        conn.execute("delete from notes.rewritten_note where note_id = any(%s)", (note_ids,))
        conn.execute("delete from eval.note_fact_rewritten where note_id = any(%s)", (note_ids,))
        for note_id, text, tagged, req in planned:
            hit = client.cached(req)
            if hit is None:
                status, reason, new_text, spans = "failed", "no clean response", None, None
            else:
                rewritten = json.loads(hit["text"])["rewritten_note"]
                v = rewrite.validate(text, tagged, rewritten, facts.get(note_id, []))
                status = "ok" if v.ok else "rejected"
                reason, new_text, spans = v.reason, v.text, v.spans
            counts[status] += 1
            if status != "ok":
                key = reason.split(":")[0] if ":" in reason else reason
                reasons[key] = reasons.get(key, 0) + 1
            conn.execute(
                """insert into notes.rewritten_note
                       (note_id, provider, model, status, reason, note_text)
                   values (%s, %s, %s, %s, %s, %s)""",
                (note_id, client.provider.name, req.model, status, reason, new_text),
            )
            if spans:
                with conn.cursor() as cur:
                    cur.executemany(
                        "insert into eval.note_fact_rewritten values (%s, %s, %s, %s)",
                        [(f"n{note_id}-f{i}", note_id, s, e) for i, (s, e) in spans.items()],
                    )
    return {**counts, "rejection_reasons": reasons}
