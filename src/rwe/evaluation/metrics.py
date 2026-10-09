"""Metrics with patient-clustered bootstrap confidence intervals (ADR-0015).

A patient contributes several questions, which are not independent (same chart, same
retrieval quirks), so CIs resample PATIENTS, not questions. Per-question bootstrapping
would give intervals that are too narrow.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def clustered_ci(
    df: pd.DataFrame,
    value: str,
    cluster: str = "person_id",
    reps: int = 2000,
    seed: int = 20261008,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Mean of `value` with a (1 - alpha) percentile CI from resampling whole clusters."""
    if df.empty:
        return float("nan"), float("nan"), float("nan")
    sums = df.groupby(cluster)[value].agg(["sum", "count"])
    s, n = sums["sum"].to_numpy(float), sums["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(reps, len(s)))
    boot = s[idx].sum(axis=1) / n[idx].sum(axis=1)
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return float(s.sum() / n.sum()), float(lo), float(hi)


def fmt(mean: float, lo: float, hi: float) -> str:
    return "n/a" if np.isnan(mean) else f"{mean:.3f} [{lo:.3f}, {hi:.3f}]"


def table(df: pd.DataFrame, value: str, by: list[str]) -> pd.DataFrame:
    rows = []
    groups = df.groupby(by) if by else [((), df)]
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        mean, lo, hi = clustered_ci(g, value)
        rows.append(
            {
                **dict(zip(by, key, strict=True)),
                "n": len(g),
                "patients": g["person_id"].nunique(),
                value: fmt(mean, lo, hi),
            }
        )
    return pd.DataFrame(rows)


def _value_in(value: str, text: str) -> bool:
    """Is the claimed value literally stated in the text? Numbers by number, text by
    case-insensitive substring (after collapsing whitespace)."""
    value, text = value.strip().lower(), " ".join(text.lower().split())
    if not value:
        return False
    nums = NUMBER.findall(value)
    if nums and all(n in NUMBER.findall(text) for n in nums):
        return True
    return " ".join(value.split()) in text


WORD = re.compile(r"[a-z]+")
STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "to",
        "of",
        "due",
        "by",
        "and",
        "or",
        "for",
        "was",
        "were",
        "on",
        "in",
        "with",
        "patient",
        "is",
        "has",
        "had",
        "first",
        "diagnosed",
        "current",
        "currently",
        "historical",
        "not",
    ]
)


def _supported(item: dict, text: str) -> bool:
    """Does the cited text support the claim? Its date is stated, or all its numbers are,
    or >= 60% of its content words are (the grader's threshold). Paraphrase-tolerant:
    the model writes "Course completed" where the note says "the course being completed"."""
    # EVERY component the claim states must be supported: a wrong number or date is not
    # rescued by matching words (a test caught "HbA1c 8.4 %" passing on the word "HbA1c").
    checks = []
    if item.get("date"):
        checks.append(item["date"] in text)
    nums = NUMBER.findall(item["value"])
    if nums:
        have_nums = NUMBER.findall(text)
        checks.append(all(n in have_nums for n in nums))
    words = {w for w in WORD.findall(item["value"].lower()) if w not in STOP and len(w) > 2}
    if words:
        checks.append(len(words & set(WORD.findall(text.lower()))) / len(words) >= 0.6)
    return bool(checks) and all(checks)


def grounding(answers: pd.DataFrame, chunk_text: dict[str, str]) -> pd.DataFrame:
    """One row per claimed item: is it cited, and is its value stated in a cited chunk?

    `answers` needs columns question_id, person_id, run_name, response, shown_chunks.
    Labels C1..Ck map to shown_chunks by position. This checks ATTRIBUTION (the cited
    excerpt says it), not truth (whether it is the right answer) -- accuracy covers that.
    """
    rows = []
    for a in answers.itertuples():
        resp = a.response or {}
        if resp.get("status") != "answered":
            continue
        for item in resp.get("items", []):
            cited = [
                a.shown_chunks[int(c[1:]) - 1]
                for c in item.get("cited_chunks", [])
                if c[1:].isdigit() and 0 < int(c[1:]) <= len(a.shown_chunks)
            ]
            texts = [chunk_text.get(c, "") for c in cited]
            supported = any(_supported(item, t) for t in texts)
            literal = any(_value_in(item["value"], t) for t in texts)
            rows.append(
                {
                    "run_name": a.run_name,
                    "question_id": a.question_id,
                    "person_id": a.person_id,
                    "value": item["value"],
                    "cited": bool(cited),
                    "grounded": float(supported),
                    "grounded_literal": float(literal),
                }
            )
    return pd.DataFrame(rows)


def abstention(df: pd.DataFrame) -> dict:
    """df: one row per answer with columns gold_nd (gold is 'not documented') and
    abstained. Precision/recall of abstaining, plus the two error kinds by name."""
    tp = int((df.gold_nd & df.abstained).sum())
    fp = int((~df.gold_nd & df.abstained).sum())  # over-abstention
    fn = int((df.gold_nd & ~df.abstained).sum())  # answered the unanswerable
    return {
        "should_abstain": int(df.gold_nd.sum()),
        "abstained": int(df.abstained.sum()),
        "precision": round(tp / (tp + fp), 3) if tp + fp else float("nan"),
        "recall": round(tp / (tp + fn), 3) if tp + fn else float("nan"),
        "over_abstentions": fp,
        "answered_unanswerable": fn,
    }
