"""Generate notes, facts and questions; store them; write and freeze the question files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from rwe.config import PipelineConfig
from rwe.notes import load, questions, render

TEST_HASH_FILE = "test_set.sha256"


class FrozenTestSetError(RuntimeError):
    """The regenerated test set differs from the frozen one."""


def generate(conn: psycopg.Connection, cfg: PipelineConfig):
    pool = load.eligible_pool(conn, cfg)
    split = load.sample_split(pool, cfg)
    patients = load.load_patients(conn, sorted(split), cfg.notes.window_start)
    traps = load.trap_conditions(conn)

    all_notes, all_questions, note_ids = [], [], {}
    next_id = 1
    for p in patients:
        notes, plan = render.render_patient(p, traps, cfg.notes, cfg.seed)
        for note in notes:
            note_ids[note.visit_id] = next_id
            next_id += 1
        cands = questions.candidates(p, notes, plan, note_ids, cfg.seed)
        all_questions += questions.select(
            cands, p.person_id, cfg.eval.questions_per_patient, cfg.seed
        )
        all_notes += notes

    facts_by_id = {
        questions.fact_id(note_ids[n.visit_id], k): f
        for n in all_notes
        for k, f in enumerate(n.facts)
    }
    questions.validate(all_questions, facts_by_id)
    return split, all_notes, note_ids, all_questions


def store(conn: psycopg.Connection, split, notes, note_ids, qs) -> None:
    with conn.transaction():
        conn.execute(
            "TRUNCATE notes.generated_note, eval.eval_patient, eval.note_fact, eval.question"
        )
        with conn.cursor().copy("COPY eval.eval_patient (person_id, split) FROM STDIN") as copy:
            for pid, s in sorted(split.items()):
                copy.write_row((pid, s))
        with conn.cursor().copy(
            "COPY notes.generated_note (note_id, person_id, visit_occurrence_id, note_date,"
            " note_kind, note_title, note_text) FROM STDIN"
        ) as copy:
            for n in notes:
                copy.write_row(
                    (note_ids[n.visit_id], n.person_id, n.visit_id, n.day, n.kind, n.title, n.text)
                )
        with conn.cursor().copy(
            "COPY eval.note_fact (fact_id, note_id, person_id, fact_type, label, surface,"
            " span_start, span_end, polarity, temporality, experiencer, source, concept_id,"
            " value, event_date, abbreviated) FROM STDIN"
        ) as copy:
            for n in notes:
                for k, f in enumerate(n.facts):
                    copy.write_row(
                        (
                            questions.fact_id(note_ids[n.visit_id], k),
                            note_ids[n.visit_id],
                            n.person_id,
                            f.fact_type,
                            f.label,
                            f.surface,
                            f.span_start,
                            f.span_end,
                            f.polarity,
                            f.temporality,
                            f.experiencer,
                            f.source,
                            f.concept_id,
                            f.value,
                            f.event_date,
                            f.abbreviated,
                        )
                    )
        for q in qs:
            conn.execute(
                "INSERT INTO eval.question VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    q.question_id,
                    split[q.person_id],
                    q.person_id,
                    q.template,
                    q.phenomenon,
                    q.question,
                    q.as_of,
                    Jsonb(q.answer),
                    q.gold_fact_ids,
                    q.sql_answerable,
                    Jsonb(q.params),
                ),
            )
    conn.commit()


def jsonl(qs, split, which: str) -> bytes:
    rows = [q.to_json(split[q.person_id]) for q in qs if split[q.person_id] == which]
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()


def write_files(out_dir: Path, split, qs, refreeze: bool = False) -> dict:
    """Write dev/test JSONL. The test file is frozen by its SHA-256: if a regenerated test
    set differs from the committed hash, stop instead of silently changing the benchmark."""
    out_dir.mkdir(parents=True, exist_ok=True)
    test_bytes = jsonl(qs, split, "test")
    digest = hashlib.sha256(test_bytes).hexdigest()
    hash_file = out_dir / TEST_HASH_FILE
    if hash_file.exists() and not refreeze:
        frozen = hash_file.read_text().split()[0]
        if frozen != digest:
            raise FrozenTestSetError(
                f"Regenerated test set {digest[:12]} differs from frozen {frozen[:12]}. "
                "Something upstream changed (data, config or code). Investigate; only "
                "re-freeze deliberately with --refreeze, before any tuning or reporting."
            )
    (out_dir / "questions_dev.jsonl").write_bytes(jsonl(qs, split, "dev"))
    (out_dir / "questions_test.jsonl").write_bytes(test_bytes)
    hash_file.write_text(f"{digest}  questions_test.jsonl\n")
    return {
        "test_sha256": digest,
        "test_questions": test_bytes.count(b"\n"),
        "dev_questions": jsonl(qs, split, "dev").count(b"\n"),
    }
