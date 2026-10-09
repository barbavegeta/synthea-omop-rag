"""Build the chunk index: chunk notes, embed incrementally, map chunks to gold facts.

Resumable by design: chunks are keyed by id + content hash, and only chunks that are new,
changed, or embedded with a different model are (re-)embedded, in committed batches. An
interrupted run loses at most one batch.
"""

from __future__ import annotations

import time

import psycopg
from pgvector.psycopg import register_vector

from rwe.config import RagConfig
from rwe.rag.chunk import Chunk, NoteRow, fixed_chunks, section_chunks
from rwe.rag.embed import Embedder

EMBED_FETCH = 1024  # chunks fetched per round; embedded in model batches of cfg.batch_size


def load_notes(conn: psycopg.Connection) -> list[NoteRow]:
    rows = conn.execute(
        """select n.note_id, n.person_id, n.note_date, g.note_kind, n.note_text
           from cdm.note n join notes.generated_note g using (note_id)
           order by n.note_id"""
    ).fetchall()
    return [NoteRow(*r) for r in rows]


MESSY_STRATEGY = "fixed_rw"  # the chosen chunking, over the LLM-rewritten notes (ADR-0014)


def make_chunks(notes: list[NoteRow], cfg: RagConfig) -> list[Chunk]:
    out = []
    for note in notes:
        if "section" in cfg.chunkings:
            out += section_chunks(note, cfg.section_max_chars)
        if "fixed" in cfg.chunkings:
            out += fixed_chunks(note, cfg.fixed_chunk_chars, cfg.fixed_overlap_chars)
    return out


def load_messy_notes(conn: psycopg.Connection) -> list[NoteRow]:
    """Every note of every patient that has rewrites: the rewritten text where it passed
    validation, the template text where it did not (so each chart stays complete)."""
    rows = conn.execute(
        """select g.note_id, g.person_id, g.note_date, g.note_kind,
                  coalesce(case when r.status = 'ok' then r.note_text end, g.note_text)
           from notes.generated_note g
           left join notes.rewritten_note r using (note_id)
           where g.person_id in (select g2.person_id from notes.generated_note g2
                                 join notes.rewritten_note r2 using (note_id))
           order by g.note_id"""
    ).fetchall()
    return [NoteRow(*r) for r in rows]


def make_messy_chunks(notes: list[NoteRow], cfg: RagConfig) -> list[Chunk]:
    return [
        c
        for n in notes
        for c in fixed_chunks(n, cfg.fixed_chunk_chars, cfg.fixed_overlap_chars, MESSY_STRATEGY)
    ]


def sync_chunks(conn: psycopg.Connection, chunks: list[Chunk], strategies: list[str]) -> dict:
    """Make the chunks of `strategies` in rag.chunk equal to `chunks`, keeping embeddings of
    unchanged chunks. Other strategies are untouched."""
    with conn.transaction():
        conn.execute(
            "CREATE TEMP TABLE chunk_new (LIKE rag.chunk INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        with conn.cursor().copy(
            "COPY chunk_new (chunk_id, strategy, note_id, person_id, note_date, section,"
            " char_start, char_end, content, content_sha) FROM STDIN"
        ) as copy:
            for c in chunks:
                copy.write_row(
                    (
                        c.chunk_id,
                        c.strategy,
                        c.note_id,
                        c.person_id,
                        c.note_date,
                        c.section,
                        c.char_start,
                        c.char_end,
                        c.content,
                        c.content_sha,
                    )
                )
        deleted = conn.execute(
            """delete from rag.chunk c
               where c.strategy = any(%s)
                 and not exists (select 1 from chunk_new n where n.chunk_id = c.chunk_id)""",
            (strategies,),
        ).rowcount
        changed = conn.execute("""
            update rag.chunk c set strategy = n.strategy, note_id = n.note_id,
                   person_id = n.person_id, note_date = n.note_date, section = n.section,
                   char_start = n.char_start, char_end = n.char_end, content = n.content,
                   content_sha = n.content_sha, embedding = null, embed_model = null
            from chunk_new n where n.chunk_id = c.chunk_id and n.content_sha <> c.content_sha
            """).rowcount
        added = conn.execute("""
            insert into rag.chunk (chunk_id, strategy, note_id, person_id, note_date, section,
                                   char_start, char_end, content, content_sha)
            select chunk_id, strategy, note_id, person_id, note_date, section, char_start,
                   char_end, content, content_sha
            from chunk_new n
            where not exists (select 1 from rag.chunk c where c.chunk_id = n.chunk_id)
            """).rowcount
    return {"chunks": len(chunks), "added": added, "changed": changed, "deleted": deleted}


def embed_missing(conn: psycopg.Connection, embedder: Embedder, log=print) -> int:
    register_vector(conn)
    done, t0 = 0, time.monotonic()
    todo = conn.execute(
        "select count(*) from rag.chunk where embed_model is distinct from %s", (embedder.name,)
    ).fetchone()[0]
    while True:
        rows = conn.execute(
            """select chunk_id, content from rag.chunk where embed_model is distinct from %s
               order by chunk_id limit %s""",
            (embedder.name, EMBED_FETCH),
        ).fetchall()
        if not rows:
            break
        vectors = embedder.passages([content for _, content in rows])
        with conn.cursor() as cur:
            cur.executemany(
                "update rag.chunk set embedding = %s, embed_model = %s where chunk_id = %s",
                [(v, embedder.name, cid) for (cid, _), v in zip(rows, vectors, strict=True)],
            )
        conn.commit()  # each round is durable: an interrupted run resumes here
        done += len(rows)
        rate = done / max(time.monotonic() - t0, 1e-9)
        log(f"  embedded {done:,}/{todo:,} chunks ({rate:.0f}/s)")
    return done


def map_facts_and_index(conn: psycopg.Connection) -> int:
    """A chunk contains a fact when the fact's whole span lies inside the chunk's range.
    For the messy strategy, spans come from the rewritten note where its rewrite passed
    validation (eval.note_fact_rewritten), else from the template note it fell back to."""
    with conn.transaction():
        conn.execute("TRUNCATE rag.chunk_fact")
        conn.execute(f"""
            insert into rag.chunk_fact (chunk_id, fact_id)
            select c.chunk_id, f.fact_id
            from rag.chunk c
            join eval.note_fact f on f.note_id = c.note_id
            left join notes.rewritten_note r
                   on r.note_id = c.note_id and r.status = 'ok'
                  and c.strategy = '{MESSY_STRATEGY}'
            left join eval.note_fact_rewritten fr
                   on fr.fact_id = f.fact_id and r.note_id is not null
            where coalesce(fr.span_start, f.span_start) >= c.char_start
              and coalesce(fr.span_end, f.span_end) <= c.char_end
            """)
        # No HNSW index (ADR-0012). Every query is patient-scoped and exact via the
        # (strategy, person_id) B-tree. With HNSW present, the planner could pick it for the
        # largest chart; HNSW then returns the ef_search=40 nearest chunks across ALL patients
        # *before* the person filter, leaving none for that patient.
        conn.execute("drop index if exists rag.chunk_embedding_hnsw")
    conn.execute("analyze rag.chunk")
    conn.execute("analyze rag.chunk_fact")
    conn.commit()
    return conn.execute("select count(*) from rag.chunk_fact").fetchone()[0]
