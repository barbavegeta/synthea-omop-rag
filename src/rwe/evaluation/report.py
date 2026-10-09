"""Final report: test-set tables and the failure analysis (ADR-0015).

Everything here reads stored results (answers, chunks, facts); nothing calls an LLM.
Outputs go to eval/results/test/ (CSV) and docs/ (Markdown).

Failure taxonomy, applied to every wrong answer in this order (first match wins):
  answered_unanswerable  gold is "not documented" but the model answered
  retrieval_miss         no gold evidence was among the excerpts shown (split below into
                         abstained = safe failure, answered = unsafe failure)
  over_abstention        the evidence WAS shown but the model said "not documented"
  negation_error         negation trap answered "yes" with the "no evidence of" evidence shown
  family_attribution     family trap answered "yes" (a relative's condition given to the patient)
  temporal_error         current/historical status, latest lab or current meds wrong, evidence shown
  other                  anything else (value, date or format error with evidence shown)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import psycopg

from rwe.answer import grade
from rwe.config import REPO_ROOT, PipelineConfig
from rwe.evaluation import metrics, sql_baseline
from rwe.rag import evaluate
from rwe.rag.index import MESSY_STRATEGY

TEMPORAL = {"condition_current", "condition_historical", "latest_lab", "current_medications"}


def load_answers(conn: psycopg.Connection, prefix: str = "test-") -> pd.DataFrame:
    rows = conn.execute(
        """select a.run_name, a.question_id, q.person_id, q.template, q.phenomenon,
                  q.question, q.answer, q.gold_fact_ids, a.response, a.shown_chunks,
                  a.correct, a.grade_detail, a.stop_reason, a.retrieval_mode,
                  exists (select 1 from rag.chunk_fact cf
                          where cf.chunk_id = any(a.shown_chunks)
                            and cf.fact_id = any(q.gold_fact_ids)) as evidence_shown
           from eval.answer a join eval.question q using (question_id)
           where a.run_name like %s order by 1, 2""",
        (prefix + "%",),
    ).fetchall()
    cols = [
        "run_name",
        "question_id",
        "person_id",
        "template",
        "phenomenon",
        "question",
        "gold",
        "gold_fact_ids",
        "response",
        "shown_chunks",
        "correct",
        "grade_detail",
        "stop_reason",
        "retrieval_mode",
        "evidence_shown",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["correct"] = df["correct"].astype(float)
    df["gold_nd"] = df["gold"].map(lambda g: g["type"] == "not_documented")
    df["abstained"] = df["response"].map(lambda r: bool(r) and r.get("status") == "not_documented")
    df["failure"] = df.apply(classify, axis=1)
    return df


def classify(r) -> str | None:
    if r.correct:
        return None
    if r.response is None:
        return "no_valid_response"
    if r.gold_nd:
        return "answered_unanswerable"
    if not r.evidence_shown:
        return "retrieval_miss"
    if r.abstained:
        return "over_abstention"
    if r.template == "negation_trap":
        return "negation_error"
    if r.template == "family_trap":
        return "family_attribution"
    if r.template in TEMPORAL:
        return "temporal_error"
    return "other"


def sql_baseline_table(conn: psycopg.Connection, cfg: PipelineConfig) -> pd.DataFrame:
    rows = []
    for q in evaluate.load_questions(conn, "test", final=True):
        ans = sql_baseline.answer(conn, cfg, q)
        ok = grade.grade(q, ans)[0] if ans is not None else None
        rows.append(
            {
                "question_id": q["question_id"],
                "person_id": q["person_id"],
                "template": q["template"],
                "sql_answerable": ans is not None,
                "correct": float(ok) if ok is not None else None,
                "gold": json.dumps(q["answer"]),
                "sql": json.dumps(ans, default=str),
            }
        )
    return pd.DataFrame(rows)


def retrieval_table(conn: psycopg.Connection, cfg: PipelineConfig, embedder) -> pd.DataFrame:
    from rwe.rag.retrieve import Retriever

    questions = evaluate.load_questions(conn, "test", final=True)
    have_messy = conn.execute(
        "select count(*) from rag.chunk where strategy = %s", (MESSY_STRATEGY,)
    ).fetchone()[0]
    frames = []
    for strategy, corpus in ((cfg.rag.chunking, "clean"), (MESSY_STRATEGY, "messy")):
        if corpus == "messy":
            if not have_messy:
                continue
            messy_people = {
                r[0]
                for r in conn.execute(
                    "select distinct person_id from rag.chunk where strategy = %s",
                    (MESSY_STRATEGY,),
                ).fetchall()
            }
            qs = [q for q in questions if q["person_id"] in messy_people]
        else:
            qs = questions
        if not qs:
            continue  # e.g. only the dev rewrite sample is indexed so far
        per_q = evaluate.evaluate(
            conn, lambda s: Retriever(conn, s, embedder, cfg.rag), strategy, qs, cfg.rag
        )
        per_q["corpus"] = corpus
        per_q["person_id"] = per_q["question_id"].map(
            {q["question_id"]: q["person_id"] for q in qs}
        )
        frames.append(per_q)
    return pd.concat(frames, ignore_index=True)


def examples(df: pd.DataFrame, chunk_text: dict[str, str], per_kind: int = 3) -> str:
    out = []
    for kind, g in df[df["failure"].notna()].groupby("failure"):
        out.append(f"### {kind} ({len(g)})\n")
        for r in g.sort_values("question_id").head(per_kind).itertuples():
            cited = []
            for item in (r.response or {}).get("items", []):
                for label in item.get("cited_chunks", []):
                    i = int(label[1:]) - 1
                    if 0 <= i < len(r.shown_chunks):
                        cited.append(r.shown_chunks[i])
            excerpt = " ".join(chunk_text.get(cited[0], "").split())[:400] if cited else ""
            out += [
                f"- **{r.question_id}** ({r.run_name}): {r.question}",
                f"  - gold: `{json.dumps(r.gold)}`",
                f"  - model: `{json.dumps(r.response)}`",
                f"  - gold evidence among excerpts shown: {r.evidence_shown}",
            ]
            if excerpt:
                out.append(f'  - first cited excerpt: "{excerpt}"')
        out.append("")
    return "\n".join(out)


def _dirs(cfg: PipelineConfig) -> tuple[Path, Path]:
    """(CSV results dir, Markdown dir). Results live under the profile's eval output dir, so
    the CI profile never overwrites the committed test results; Markdown goes to docs/ only
    for the default profile."""
    out = cfg.eval.resolved_output_dir() / "results" / "test"
    docs = REPO_ROOT / "docs" if cfg.profile == "default" else out
    return out, docs


def write_all(conn: psycopg.Connection, cfg: PipelineConfig, embedder, log=print) -> dict:
    out, docs = _dirs(cfg)
    out.mkdir(parents=True, exist_ok=True)
    ans = load_answers(conn)
    ids = sorted({c for s in ans["shown_chunks"] for c in s})
    chunk_text = dict(
        conn.execute(
            "select chunk_id, content from rag.chunk where chunk_id = any(%s)", (ids,)
        ).fetchall()
    )

    acc = metrics.table(ans, "correct", ["run_name"])
    acc_t = metrics.table(ans, "correct", ["run_name", "template"])
    acc_p = metrics.table(ans, "correct", ["run_name", "phenomenon"])
    ground = metrics.grounding(ans, chunk_text)
    ground_t = metrics.table(ground, "grounded", ["run_name"]) if len(ground) else pd.DataFrame()
    abst = pd.DataFrame(
        [{"run_name": k, **metrics.abstention(g)} for k, g in ans.groupby("run_name")]
    )
    fails = (
        ans[ans["failure"].notna()]
        .groupby(["run_name", "failure"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    miss = ans[ans["failure"] == "retrieval_miss"]
    miss_split = (
        miss.assign(
            outcome=miss["abstained"].map(
                {True: "abstained (safe)", False: "answered wrongly (unsafe)"}
            )
        )
        .groupby(["run_name", "outcome"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    sql = sql_baseline_table(conn, cfg)
    sql_t = metrics.table(sql[sql["sql_answerable"]], "correct", ["template"])
    sql[sql["sql_answerable"] & (sql["correct"] == 0)].to_csv(
        out / "sql_vs_gold_disagreements.csv", index=False
    )
    agree = grounding_agreement(out)
    retrieval = retrieval_table(conn, cfg, embedder)
    ret_t = evaluate.summarise(retrieval, cfg.rag.k_values, ["corpus", "mode"])
    ret_ci = pd.DataFrame(
        [
            {
                "corpus": c,
                "mode": m,
                "recall@5 [95% CI]": metrics.fmt(
                    *metrics.clustered_ci(
                        g.assign(hit=(g["rank"].notna() & (g["rank"] <= 5)).astype(float)), "hit"
                    )
                ),
            }
            for (c, m), g in retrieval.groupby(["corpus", "mode"])
        ]
    )

    for name, frame in {
        "accuracy": acc,
        "accuracy_by_template": acc_t,
        "accuracy_by_phenomenon": acc_p,
        "grounding": ground_t,
        "abstention": abst,
        "failures": fails,
        "retrieval_miss_outcome": miss_split,
        "sql_baseline": sql_t,
        "retrieval": ret_t,
        "retrieval_recall5_ci": ret_ci,
    }.items():
        frame.to_csv(out / f"{name}.csv", index=False)
    ans.drop(columns=["response", "gold", "grade_detail"]).to_csv(
        out / "answers_per_question.csv", index=False
    )

    md = lambda f: f.to_markdown(index=False) if len(f) else "_(none yet)_"  # noqa: E731
    results = [
        "# Test-set results",
        "",
        "Synthetic data (Synthea): these numbers describe this pipeline on synthetic, "
        "templated notes, not clinical performance. 95% CIs are patient-clustered "
        "bootstraps (ADR-0015).",
        "",
        "## Retrieval (all configurations; no LLM involved)",
        md(ret_t),
        "",
        md(ret_ci),
        "",
        "## Answer accuracy",
        md(acc),
        "",
        "### By template",
        md(acc_t),
        "",
        "### By phenomenon",
        md(acc_p),
        "",
        "## Grounding of claims",
        md(ground_t),
        "",
        "## Abstention",
        md(abst),
        "",
        "## Plain SQL baseline (structured templates)",
        "Same definitions as the gold, so this is the ceiling by construction; "
        "note-only templates (family history, stop reasons) are not answerable from "
        "the CDM. Disagreements with gold: `eval/results/test/sql_vs_gold_disagreements.csv`.",
        md(sql_t),
        "",
        "## Grounding check vs independent labels (sample of 50 claims)",
        agree or "_(not labelled yet)_",
        "",
    ]
    (docs / "results.md").write_text("\n".join(results))
    taxonomy = "Failure taxonomy" + __doc__.split("Failure taxonomy", 1)[1]
    failure_doc = [
        "# Failure analysis (test set)",
        "",
        "```",
        taxonomy.strip(),
        "```",
        "",
        "## Counts",
        md(fails),
        "",
        "## What the model did when retrieval missed the evidence",
        md(miss_split),
        "",
        "## Examples",
        examples(ans, chunk_text),
    ]
    (docs / "failure_analysis.md").write_text("\n".join(failure_doc))
    log(
        f"wrote {out} and {docs}/results.md, failure_analysis.md "
        f"({len(ans)} answers across {ans['run_name'].nunique()} runs)"
    )
    return {"runs": sorted(ans["run_name"].unique().tolist()), "answers": len(ans)}


def write_grounding_sample(
    conn: psycopg.Connection, cfg: PipelineConfig, run_name: str, n: int = 50
) -> Path:
    """A random sample of claims for a HUMAN to label supported / not supported, without
    showing the automatic label (kept in a separate file) so the human is not anchored.
    Refuses to overwrite a sample that already has labels in it."""
    out, _ = _dirs(cfg)
    target = out / "grounding_sample_TO_LABEL.csv"
    if target.exists():
        col = pd.read_csv(target, dtype=str)["supported_by_excerpts (yes/no)"]
        if col.fillna("").str.strip().ne("").any():
            raise FileExistsError(f"{target} already has labels; move it away to resample")
    seed = cfg.seed
    ans = load_answers(conn)
    ans = ans[ans["run_name"] == run_name]
    ids = sorted({c for s in ans["shown_chunks"] for c in s})
    chunk_text = dict(
        conn.execute(
            "select chunk_id, content from rag.chunk where chunk_id = any(%s)", (ids,)
        ).fetchall()
    )
    g = metrics.grounding(ans, chunk_text).reset_index(drop=True)
    g["claim_id"] = [f"c{i:03d}" for i in range(len(g))]
    sample = g.sample(n=min(n, len(g)), random_state=seed).sort_values("claim_id")
    rows, auto = [], []
    for r in sample.itertuples():
        a = ans[ans["question_id"] == r.question_id].iloc[0]
        item = next(i for i in a.response["items"] if i["value"] == r.value)
        cited = "\n---\n".join(
            chunk_text.get(a.shown_chunks[int(c[1:]) - 1], "") for c in item["cited_chunks"]
        )
        rows.append(
            {
                "claim_id": r.claim_id,
                "question": a.question,
                "claim": r.value,
                "claim_date": item["date"],
                "cited_excerpts": cited,
                "supported_by_excerpts (yes/no)": "",
            }
        )
        auto.append({"claim_id": r.claim_id, "auto_grounded": int(r.grounded)})
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(target, index=False)
    pd.DataFrame(auto).to_csv(out / "grounding_sample_auto_labels.csv", index=False)
    return target


# Who labelled each file. The human file is the calibration the design calls for; the
# Claude file is a second, weaker check (an LLM reader, same model family as the answerer).
LABELLERS = {
    "grounding_sample_TO_LABEL.csv": "human (hand labels)",
    "grounding_sample_claude_labels.csv": "Claude Opus 5.5 (LLM reader, not a human)",
}


def grounding_agreement(out: Path) -> str | None:
    """Agreement between the automatic grounding label and each labeller's labels."""
    auto = out / "grounding_sample_auto_labels.csv"
    if not auto.exists():
        return None
    col = "supported_by_excerpts (yes/no)"
    lines = []
    for name, who in LABELLERS.items():
        if not (out / name).exists():
            continue
        h = pd.read_csv(out / name, dtype=str).merge(pd.read_csv(auto), on="claim_id")
        h = h[h[col].fillna("").str.strip().str.lower().isin(["yes", "no"])]
        if h.empty:
            continue
        lab = (h[col].str.strip().str.lower() == "yes").astype(int)
        a = h["auto_grounded"].astype(int)
        po = float((lab == a).mean())
        pe = float(lab.mean() * a.mean() + (1 - lab.mean()) * (1 - a.mean()))
        kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
        disagree = ", ".join(h.loc[lab != a, "claim_id"])
        lines.append(
            f"- {who}: {len(h)} claims; agreement {po:.2f}, Cohen's kappa {kappa:.2f}; "
            f"labeller says supported {lab.mean():.2f}, automatic rule {a.mean():.2f}"
            + (f"; disagreements: {disagree}" if disagree else "")
        )
    return "\n".join(lines) or None
