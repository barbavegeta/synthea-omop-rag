"""Single entrypoint for the pipeline: `rwe <command>`. `rwe all` runs every step in order.

Each config profile works in its own database (config `database`), so the 20-patient CI
profile can never overwrite the full run's data. Commands are added phase by phase.
"""

from __future__ import annotations

import json
import os
import subprocess
from decimal import Decimal
from typing import Annotated

import pandas as pd
import typer
from dotenv import load_dotenv

from rwe import db
from rwe.analysis import t2dm
from rwe.config import REPO_ROOT, PipelineConfig, load_config
from rwe.ingest import fhir_loader
from rwe.manifest import build_manifest, write_manifest
from rwe.notes import pipeline as notes_pipeline
from rwe.synthea import run as synthea
from rwe.vocab import load_athena, stub

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)

Profile = Annotated[
    str | None,
    typer.Option("--profile", "-p", envvar="RWE_PROFILE", help="Config profile (default, ci)."),
]

CI_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "fhir_ci"
DBT_DIR = REPO_ROOT / "dbt"


@app.command("config")
def show_config(profile: Profile = None) -> None:
    """Print the resolved config and its fingerprint."""
    cfg = load_config(profile)
    typer.echo(json.dumps(cfg.model_dump(mode="json"), indent=2))
    typer.echo(f"fingerprint: {cfg.fingerprint()}")


def _db_init(cfg: PipelineConfig) -> None:
    db.ensure_database(cfg.database)
    with db.connect(dbname=cfg.database) as conn:
        db.bootstrap(conn)
        version = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    typer.echo(f"database {cfg.database} ready (pgvector {version[0]})")


@app.command("db-init")
def db_init(profile: Profile = None) -> None:
    """Create the profile's database, extensions, base schemas and raw tables (idempotent)."""
    _db_init(load_config(profile))


def _generate(cfg: PipelineConfig) -> dict:
    out_dir = cfg.ingest.resolved_fhir_dir().parent
    info = synthea.generate(cfg.synthea, out_dir)
    typer.echo(f"synthea {'up to date' if info['skipped'] else 'generated'}: {out_dir}")
    return info


@app.command("synthea")
def run_synthea(profile: Profile = None) -> None:
    """Generate patients with Synthea (skipped when inputs are unchanged)."""
    _generate(load_config(profile))


def _ingest(cfg: PipelineConfig) -> dict:
    fhir_dir = cfg.ingest.resolved_fhir_dir()
    with db.connect(dbname=cfg.database) as conn:
        summary = fhir_loader.load(conn, fhir_dir)
    typer.echo(f"loaded {summary.n_resources:,} resources from {summary.n_bundles} bundles")
    for resource_type, n in summary.by_type.most_common():
        typer.echo(f"  {resource_type:<26}{n:>10,}")
    return {
        "fhir_dir": str(fhir_dir),
        "n_bundles": summary.n_bundles,
        "n_resources": summary.n_resources,
        "input_digest": summary.input_digest,
    }


@app.command("ingest")
def ingest(profile: Profile = None) -> None:
    """Load FHIR bundles into raw.fhir_resource (full refresh)."""
    _ingest(load_config(profile))


def _vocab(cfg: PipelineConfig, force: bool = False) -> dict:
    with db.connect(dbname=cfg.database) as conn:
        if cfg.vocab.source == "stub":
            info = stub.load(conn)
            typer.echo(f"built stub vocabulary: {info['concepts']} concepts (CI only)")
            return {"source": "stub", "release": info["release"]}
        info = load_athena.load(conn, cfg.vocab.resolved_dir(), force=force)
    if info["skipped"]:
        typer.echo(f"vocabulary up to date ({info['release']})")
    else:
        typer.echo(f"loaded Athena release {info['release']}")
        for table, n in info["rows"].items():
            typer.echo(f"  {table:<24}{n:>12,}")
    return {"source": cfg.vocab.source, "release": info["release"]}


@app.command("vocab")
def vocab(
    profile: Profile = None,
    force: Annotated[bool, typer.Option(help="Reload even if unchanged.")] = False,
) -> None:
    """Load vocabularies into the vocab schema: Athena (skipped when unchanged) or the CI stub."""
    _vocab(load_config(profile), force=force)


def _dbt(cfg: PipelineConfig, *args: str) -> None:
    """Run dbt against this project and the profile's database. dbt does not read .env,
    so it is loaded here; PGDATABASE is pointed at the profile's database."""
    load_dotenv(REPO_ROOT / ".env", override=False)
    env = {**os.environ, "PGDATABASE": cfg.database}
    command = ["dbt", *args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    result = subprocess.run(command, check=False, env=env)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


@app.command("dbt", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def dbt(ctx: typer.Context) -> None:
    """Pass-through to dbt, e.g. `rwe dbt build --select cdm`.
    The profile comes from RWE_PROFILE (dbt has its own --profile flag)."""
    _dbt(load_config(), *ctx.args)


def _coverage(cfg: PipelineConfig) -> list[dict]:
    with db.connect(dbname=cfg.database) as conn:
        cur = conn.execute("SELECT * FROM dq.dq_mapping_coverage ORDER BY records DESC")
        names = [c.name for c in cur.description]
        return [
            {k: float(v) if isinstance(v, Decimal) else v for k, v in zip(names, row, strict=True)}
            for row in cur.fetchall()
        ]


def _analyse(cfg: PipelineConfig) -> dict:
    with db.connect(dbname=cfg.database) as conn:
        info = t2dm.run(
            conn, cfg.analysis.resolved_output_dir(), cfg.analysis.min_cell_count, cfg.fingerprint()
        )
    typer.echo(f"T2DM analysis: {info['cohort_persons']} persons -> {info['output_dir']}")
    return info


@app.command("analyse")
def analyse(profile: Profile = None) -> None:
    """Phase 3 RWE analysis: T2DM cohort, metformin, HbA1c (needs the dbt build)."""
    _analyse(load_config(profile))


def _notes(cfg: PipelineConfig, refreeze: bool = False) -> dict:
    with db.connect(dbname=cfg.database) as conn:
        split, notes, note_ids, qs = notes_pipeline.generate(conn, cfg)
        notes_pipeline.store(conn, split, notes, note_ids, qs)
    info = notes_pipeline.write_files(cfg.eval.resolved_output_dir(), split, qs, refreeze=refreeze)
    n_facts = sum(len(n.facts) for n in notes)
    typer.echo(
        f"notes: {len(notes):,} notes, {n_facts:,} facts for {len(split)} patients; "
        f"questions: {info['dev_questions']} dev / {info['test_questions']} test "
        f"(test sha256 {info['test_sha256'][:12]})"
    )
    return {**info, "notes": len(notes), "facts": n_facts, "patients": len(split)}


@app.command("notes")
def notes(
    profile: Profile = None,
    refreeze: Annotated[
        bool, typer.Option(help="Accept a changed test set. Only before any tuning/reporting.")
    ] = False,
) -> None:
    """Phase 4: generate notes, ground-truth facts and the frozen question set."""
    cfg = load_config(profile)
    _notes(cfg, refreeze=refreeze)
    _dbt(cfg, "build", "--select", "note+")


def _index(cfg: PipelineConfig, messy: bool = False) -> dict:
    from rwe.rag import embed, index

    with db.connect(dbname=cfg.database) as conn:
        db.bootstrap(conn)
        if messy:  # the rewritten notes, as their own strategy (template chunks untouched)
            notes_ = index.load_messy_notes(conn)
            chunks = index.make_messy_chunks(notes_, cfg.rag)
            sync = index.sync_chunks(conn, chunks, [index.MESSY_STRATEGY])
        else:
            notes_ = index.load_notes(conn)
            chunks = index.make_chunks(notes_, cfg.rag)
            sync = index.sync_chunks(conn, chunks, list(cfg.rag.chunkings))
        typer.echo(
            f"chunks: {sync['chunks']:,} ({sync['added']:,} new, {sync['changed']:,} "
            f"changed, {sync['deleted']:,} removed) from {len(notes_):,} notes"
        )
        embedder = embed.make_embedder(cfg.rag)
        embedded = index.embed_missing(conn, embedder, log=typer.echo)
        mapped = index.map_facts_and_index(conn)
    typer.echo(f"embedded {embedded:,} chunks with {embedder.name}; {mapped:,} chunk-fact links")
    return {**sync, "embedder": embedder.name, "chunk_fact_links": mapped}


@app.command("index")
def build_index(
    profile: Profile = None,
    messy: Annotated[bool, typer.Option(help="Index the LLM-rewritten notes (Phase 6b).")] = False,
) -> None:
    """Phase 5: chunk notes, embed (resumable), map chunks to gold facts, build HNSW."""
    _index(load_config(profile), messy=messy)


def _retrieval_dev(cfg: PipelineConfig) -> dict:
    from rwe.rag import embed, evaluate
    from rwe.rag.retrieve import Retriever

    out_dir = cfg.eval.resolved_output_dir() / "results" / "dev"
    out_dir.mkdir(parents=True, exist_ok=True)
    with db.connect(dbname=cfg.database) as conn:
        questions = evaluate.load_questions(conn, "dev")
        embedder = embed.make_embedder(cfg.rag)
        frames = [
            evaluate.evaluate(
                conn, lambda s: Retriever(conn, s, embedder, cfg.rag), s, questions, cfg.rag
            )
            for s in cfg.rag.chunkings
        ]
    per_q = pd.concat(frames, ignore_index=True)
    overall = evaluate.summarise(per_q, cfg.rag.k_values, ["strategy", "mode"])
    by_template = evaluate.summarise(per_q, cfg.rag.k_values, ["strategy", "mode", "template"])
    per_q.to_csv(out_dir / "retrieval_per_question.csv", index=False)
    overall.to_csv(out_dir / "retrieval_overall.csv", index=False)
    by_template.to_csv(out_dir / "retrieval_by_template.csv", index=False)
    typer.echo(overall.to_markdown(index=False))
    return {
        "dev_questions_scored": int(per_q["question_id"].nunique()),
        "overall": overall.to_dict(orient="records"),
    }


@app.command("retrieval-dev")
def retrieval_dev(profile: Profile = None) -> None:
    """Phase 5: retrieval recall@k / MRR on the DEV split only (test is scored in Phase 7)."""
    _retrieval_dev(load_config(profile))


@app.command("answer")
def answer(
    run_name: Annotated[str, typer.Option(help="Name stored with every answer of this run.")],
    profile: Profile = None,
    model: Annotated[str | None, typer.Option(help="Overrides llm.model / LLM_MODEL.")] = None,
    effort: Annotated[str | None, typer.Option(help="Overrides llm.effort.")] = None,
    mode: Annotated[
        str | None, typer.Option(help="Retrieval mode; default llm.retrieval_mode.")
    ] = None,
    per_template: Annotated[int, typer.Option(help="Stratified sample size; 0 = all dev.")] = 0,
    workers: Annotated[int, typer.Option(help="Parallel LLM calls.")] = 6,
    dry_run: Annotated[bool, typer.Option(help="Price the run; send nothing.")] = False,
) -> None:
    """Phase 6: answer DEV questions with citations and grade them (test is Phase 7)."""
    from rwe.answer import run
    from rwe.llm.client import LlmClient
    from rwe.llm.providers import make_provider
    from rwe.rag import embed, evaluate
    from rwe.rag.retrieve import Retriever

    cfg = load_config(profile)
    llm_cfg = cfg.llm.with_env()
    model = model or llm_cfg.model
    effort = effort or llm_cfg.effort
    mode = mode or llm_cfg.retrieval_mode
    with db.connect(dbname=cfg.database) as conn, db.connect(dbname=cfg.database) as llm_conn:
        db.bootstrap(conn)
        questions = evaluate.load_questions(conn, "dev")
        if per_template:
            questions = run.stratified_sample(questions, per_template, cfg.seed)
        retriever = Retriever(conn, cfg.rag.chunking, embed.make_embedder(cfg.rag), cfg.rag)
        planned = run.build_requests(conn, retriever, cfg, questions, model, effort, mode, run_name)
        client = LlmClient(llm_conn, llm_cfg, make_provider(llm_cfg) if not dry_run else _NoCall())
        est = run.estimate(client, planned)
        typer.echo(
            f"run {run_name}: {len(planned)} questions, model {model}, effort {effort}, "
            f"retrieval {mode}, provider {llm_cfg.provider}"
        )
        typer.echo("  " + ", ".join(f"{k}={v}" for k, v in est.items()))
        if dry_run:
            return
        results = run.execute(conn, client, planned, run_name, mode, workers, log=typer.echo)
    by_template = results.groupby("template")["correct"].agg(["mean", "count"]).round(3)
    typer.echo(by_template.to_markdown())
    typer.echo(
        f"accuracy {results['correct'].mean():.3f} on {len(results)} questions; "
        f"this run cost ${results['cost_usd'].sum():.4f} "
        f"({int(results['cached'].sum())} cached)"
    )


class _NoCall:
    """Stands in for a provider during dry runs: pricing only, never called."""

    name = "anthropic"
    billable = True

    def call(self, req):  # pragma: no cover - a dry run must never reach this
        raise RuntimeError("dry run attempted an API call")


@app.command("rewrite")
def rewrite_notes(
    scope: Annotated[str, typer.Option(help="dev-sample (direct calls) or test (batch).")],
    profile: Profile = None,
    dry_run: Annotated[bool, typer.Option(help="Price it; send nothing.")] = False,
    submit: Annotated[bool, typer.Option(help="test scope: submit the batch and return.")] = False,
    collect: Annotated[bool, typer.Option(help="test scope: collect a finished batch.")] = False,
) -> None:
    """Phase 6b: rewrite notes into messier text with fact tags, validate, store."""
    from rwe.llm.client import BatchRunner, LlmClient
    from rwe.llm.providers import make_provider
    from rwe.notes import rewrite_run

    cfg = load_config(profile)
    llm_cfg = cfg.llm.with_env()
    with db.connect(dbname=cfg.database) as conn, db.connect(dbname=cfg.database) as llm_conn:
        db.bootstrap(conn)
        patients = rewrite_run.scope_patients(conn, scope, cfg.seed)
        notes_, facts = rewrite_run.load(conn, patients)
        planned = rewrite_run.build(cfg, notes_, facts, scope)
        provider = _NoCall() if dry_run else make_provider(llm_cfg)
        client = LlmClient(llm_conn, llm_cfg, provider)
        todo = [p[3] for p in planned if client.cached(p[3]) is None]
        batch = BatchRunner(client)
        price_in, price_out = llm_cfg.price(llm_cfg.rewrite_model)
        factor = 0.5 if scope == "test" else 1.0  # batch discount on the test scope
        in_tok = sum(r.estimated_input_tokens() for r in todo)
        expected = (in_tok * price_in + len(todo) * 600 * price_out) / 1e6 * factor
        worst = sum(batch.worst_case(r) if scope == "test" else client.reservation(r) for r in todo)
        typer.echo(
            f"rewrite {scope}: {len(patients)} patients, {len(planned)} notes, "
            f"{len(todo)} to send; expected ~${expected:.2f}, worst case ${worst:.2f}; "
            f"spent/reserved so far ${client.spent:.4f} of ${llm_cfg.budget_usd:.2f}"
        )
        if dry_run:
            return
        if scope == "test":
            if submit:
                batch_id, waiting = batch.submit([p[3] for p in planned], label=f"rewrite:{scope}")
                if batch_id is None:
                    typer.echo("nothing to submit (all answered, in flight, or truncated before)")
                    return
                typer.echo(
                    f"submitted batch {batch_id}; {waiting} requests still waiting for "
                    "headroom. Run --collect when it ends, then --submit again if needed."
                )
                return
            if collect:
                open_batches = [
                    r[0]
                    for r in llm_conn.execute(
                        "select batch_id from llm.batch where label = %s and status = 'submitted'",
                        (f"rewrite:{scope}",),
                    ).fetchall()
                ]
                for batch_id in open_batches:
                    status, counts = batch.collect(batch_id, log=typer.echo)
                    typer.echo(f"batch {batch_id}: {status} {counts}")
                    if status != "collected":
                        return
        else:
            rewrite_run.send_direct(client, planned)
        result = rewrite_run.process(conn, client, planned, facts)
    typer.echo(f"rewrite {scope}: {result}")


@app.command("final")
def final(
    corpus: Annotated[str, typer.Option(help="clean (template notes) or messy (rewritten).")],
    mode: Annotated[str, typer.Option(help="Retrieval: bm25 | dense | hybrid | hybrid_recency.")],
    profile: Profile = None,
    dry_run: Annotated[bool, typer.Option(help="Price it; send nothing.")] = False,
    submit: Annotated[bool, typer.Option(help="Submit (the next chunk of) the batch.")] = False,
    collect: Annotated[bool, typer.Option(help="Collect finished batches, grade, store.")] = False,
) -> None:
    """Phase 7: answer the TEST set once (batch), for one corpus and retrieval mode."""
    from rwe.answer import run
    from rwe.llm.client import BatchRunner, LlmClient
    from rwe.llm.providers import make_provider
    from rwe.rag import embed, evaluate
    from rwe.rag.index import MESSY_STRATEGY
    from rwe.rag.retrieve import Retriever

    cfg = load_config(profile)
    llm_cfg = cfg.llm.with_env()
    strategy = {"clean": cfg.rag.chunking, "messy": MESSY_STRATEGY}[corpus]
    run_name = f"test-{corpus}-{mode}"
    with db.connect(dbname=cfg.database) as conn, db.connect(dbname=cfg.database) as llm_conn:
        db.bootstrap(conn)
        questions = evaluate.load_questions(conn, "test", final=True)
        retriever = Retriever(conn, strategy, embed.make_embedder(cfg.rag), cfg.rag)
        planned = run.build_requests(
            conn, retriever, cfg, questions, llm_cfg.model, llm_cfg.effort, mode, run_name
        )
        client = LlmClient(llm_conn, llm_cfg, _NoCall() if dry_run else make_provider(llm_cfg))
        batch = BatchRunner(client)
        todo = [req for _, _, req in planned if client.cached(req) is None]
        price_in, price_out = llm_cfg.price(llm_cfg.model)
        in_tok = sum(r.estimated_input_tokens() for r in todo)
        expected = (
            (in_tok * price_in + len(todo) * run.ASSUMED_OUTPUT_TOKENS * price_out) / 1e6 * 0.5
        )
        typer.echo(
            f"{run_name}: {len(planned)} questions, {len(todo)} not yet answered; "
            f"expected ~${expected:.2f} (batch), worst case "
            f"${sum(batch.worst_case(r) for r in todo):.2f}; spent/reserved "
            f"${client.spent:.4f} of ${llm_cfg.budget_usd:.2f}"
        )
        if dry_run:
            return
        if submit:
            batch_id, waiting = batch.submit([req for _, _, req in planned], label=run_name)
            if batch_id is None:
                typer.echo("nothing to submit (all answered, in flight, or truncated before)")
                return
            typer.echo(f"submitted batch {batch_id}; {waiting} waiting for headroom")
            return
        if collect:
            for (batch_id,) in llm_conn.execute(
                "select batch_id from llm.batch where label = %s and status = 'submitted'",
                (run_name,),
            ).fetchall():
                status, counts = batch.collect(batch_id, log=typer.echo)
                typer.echo(f"batch {batch_id}: {status} {counts}")
                if status != "collected":
                    return
        results = run.record_from_cache(conn, client, planned, run_name, mode)
    typer.echo(
        f"{run_name}: {int(results['answered'].sum())}/{len(results)} answered; "
        f"accuracy so far {results['correct'].mean():.3f}"
    )


@app.command("report")
def report(profile: Profile = None) -> None:
    """Phase 7: write the test-set tables, docs/results.md and docs/failure_analysis.md.
    Reads stored answers only; no LLM calls. Re-run after each collected batch."""
    from rwe.evaluation import report as rep
    from rwe.rag import embed

    cfg = load_config(profile)
    with db.connect(dbname=cfg.database) as conn:
        out = rep.write_all(conn, cfg, embed.make_embedder(cfg.rag), log=typer.echo)
    typer.echo(json.dumps(out, indent=2))


@app.command("grounding-sample")
def grounding_sample(
    run_name: Annotated[str, typer.Option(help="Run to sample claims from.")],
    n: Annotated[int, typer.Option(help="Claims to sample.")] = 50,
    profile: Profile = None,
) -> None:
    """Phase 7: a random claim sample for you to label by hand (calibrates grounding)."""
    from rwe.evaluation import report as rep

    cfg = load_config(profile)
    with db.connect(dbname=cfg.database) as conn:
        path = rep.write_grounding_sample(conn, cfg, run_name, n=n)
    typer.echo(f"label this file: {path}")


@app.command("llm-spend")
def llm_spend(profile: Profile = None) -> None:
    """Show total LLM spend against the cap, by purpose and model."""
    cfg = load_config(profile)
    with db.connect(dbname=cfg.database) as conn:
        db.bootstrap(conn)
        rows = conn.execute(
            """select purpose, model_served, status, count(*), sum(input_tokens),
                      sum(output_tokens), round(sum(cost_usd), 4)
               from llm.spend_ledger group by 1, 2, 3 order by 1, 2, 3"""
        ).fetchall()
        total = conn.execute("select coalesce(sum(cost_usd), 0) from llm.spend_ledger").fetchone()[
            0
        ]
    table = pd.DataFrame(
        rows,
        columns=[
            "purpose",
            "model",
            "status",
            "calls",
            "input_tokens",
            "output_tokens",
            "cost_usd",
        ],
    )
    typer.echo(table.to_markdown(index=False) if len(table) else "no calls yet")
    typer.echo(f"total ${float(total):.4f} of ${cfg.llm.with_env().budget_usd:.2f} cap")


@app.command("fixture")
def make_fixture() -> None:
    """Regenerate the committed CI fixture: Synthea with the ci profile, gzipped."""
    cfg = load_config("ci")
    out_dir = synthea.DATA_DIR / "ci"
    synthea.generate(cfg.synthea, out_dir)
    written = synthea.write_fixture(out_dir / "fhir", CI_FIXTURE_DIR)
    size_mb = sum(p.stat().st_size for p in written) / 1e6
    typer.echo(f"wrote {len(written)} bundles ({size_mb:.1f} MB) to {CI_FIXTURE_DIR}")


@app.command("all")
def run_all(profile: Profile = None) -> None:
    """Run the whole pipeline end to end."""
    cfg = load_config(profile)
    _db_init(cfg)
    extra: dict = {"database": cfg.database}
    if cfg.synthea.generate:
        extra["synthea"] = _generate(cfg)
    extra["ingest"] = _ingest(cfg)
    extra["vocab"] = _vocab(cfg)
    _dbt(cfg, "deps")
    _dbt(cfg, "build")
    extra["mapping_coverage"] = _coverage(cfg)
    extra["t2dm_analysis"] = _analyse(cfg)
    extra["notes"] = _notes(cfg)
    _dbt(cfg, "build", "--select", "note+")  # rebuild cdm.note from the fresh notes
    extra["index"] = _index(cfg)
    path = write_manifest(build_manifest(cfg, extra))
    typer.echo(f"profile={cfg.profile} fingerprint={cfg.fingerprint()} manifest={path}")


if __name__ == "__main__":
    app()
