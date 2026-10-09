"""Question templates with gold answers and gold supporting facts (ADR-0011).

Every question has:
  answer          the gold answer, computed from the same CDM-derived data the notes were
                  written from (structured facts) or from the planted note-only content
  gold_fact_ids   the note facts that support it: these define retrieval relevance (P5)
                  and what a grounded answer may cite (P7); empty for "not documented"
  phenomenon      what it tests: lookup | temporality | negation | family_history |
                  note_only | abstention
  sql_answerable  whether a plain SQL query on the CDM can answer it (the P7 baseline)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rwe.notes.load import LABS
from rwe.notes.model import Fact, Note, Patient
from rwe.notes.render import PatientPlan, rng_for

CORE = ["latest_lab", "dx_date", "current_medications", "negation_trap", "lab_not_documented"]
OPTIONAL = [
    "condition_current",
    "condition_historical",
    "family_trap",
    "family_history",
    "stop_reason",
    "stop_reason_undocumented",
]


@dataclass(frozen=True)
class Question:
    question_id: str
    person_id: int
    template: str
    phenomenon: str
    question: str
    as_of: date
    answer: dict
    gold_fact_ids: list[str]
    sql_answerable: bool
    params: dict

    def to_json(self, split: str) -> dict:
        return {
            "question_id": self.question_id,
            "split": split,
            "person_id": self.person_id,
            "template": self.template,
            "phenomenon": self.phenomenon,
            "question": self.question,
            "as_of": self.as_of.isoformat(),
            "answer": self.answer,
            "gold_fact_ids": self.gold_fact_ids,
            "sql_answerable": self.sql_answerable,
            "params": self.params,
        }


def fact_ids(notes: list[Note], note_ids: dict[int, int], pred) -> list[str]:
    out = []
    for note in notes:
        for k, f in enumerate(note.facts):
            if pred(note, f):
                out.append(fact_id(note_ids[note.visit_id], k))
    return out


def fact_id(note_id: int, index: int) -> str:
    return f"n{note_id}-f{index}"


def candidates(
    p: Patient, notes: list[Note], plan: PatientPlan, note_ids: dict[int, int], seed: int
) -> dict:
    """Every question this patient can support, keyed by template."""
    out: dict[str, Question] = {}
    as_of = p.as_of
    last = notes[-1]

    def q(template, phenomenon, text, answer, gold, sql, **params):
        out[template] = Question(
            f"p{p.person_id}-{template}",
            p.person_id,
            template,
            phenomenon,
            text,
            as_of,
            answer,
            gold,
            sql,
            params,
        )

    rng = rng_for(seed, p.person_id, "questions")  # choice of which item to ask about

    # latest lab value
    if p.labs:
        label = rng.choice(sorted({lab.label for lab in p.labs}))
        # The LAST value on the latest date: when a lab is repeated at one visit, the note
        # prints the last one (render keeps the last per visit), so the gold must too.
        # (A first-of-day tie-break made 1 test gold value absent from every note; found by
        # a gold-vs-notes consistency check before any test scoring -- ADR-0015.)
        candidates = [(lab.day, i, lab) for i, lab in enumerate(p.labs) if lab.label == label]
        latest = max(candidates, key=lambda t: (t[0], t[1]))[2]
        gold = fact_ids(
            notes,
            note_ids,
            lambda n, f: (
                f.fact_type == "lab_value" and f.label == label and f.event_date == latest.day
            ),
        )
        q(
            "latest_lab",
            "lookup",
            f"What was this patient's most recent {label} result, and on what date?",
            {
                "type": "lab",
                "value": latest.value,
                "unit": latest.unit,
                "date": latest.day.isoformat(),
            },
            gold,
            True,
            loinc=latest.loinc,
        )

    # first diagnosis date (only conditions recorded once, so 'first' is unambiguous)
    counts: dict[int, int] = {}
    for c in p.conditions:
        counts[c.concept_id] = counts.get(c.concept_id, 0) + 1
    single = sorted(
        {c.concept_id: c for c in p.conditions if counts[c.concept_id] == 1}.values(),
        key=lambda c: c.concept_id,
    )
    mentioned = [
        c
        for c in single
        if any(
            f.concept_id == c.concept_id and f.fact_type == "condition" and f.polarity == "affirmed"
            for n in notes
            for f in n.facts
        )
    ]
    if mentioned:
        c = rng.choice(mentioned)
        gold = fact_ids(
            notes,
            note_ids,
            lambda n, f: (
                f.fact_type == "condition"
                and f.concept_id == c.concept_id
                and f.polarity == "affirmed"
            ),
        )
        q(
            "dx_date",
            "lookup",
            f"When was this patient first diagnosed with {c.name.lower()}?",
            {"type": "date", "date": c.start.isoformat()},
            gold,
            True,
            concept_id=c.concept_id,
        )

    # current medications as of the last note
    current = sorted({e.ingredient for e in p.prescriptions if e.active_on(as_of)})
    gold = fact_ids(
        [last], note_ids, lambda n, f: f.fact_type in ("medication_current", "medication_none")
    )
    q(
        "current_medications",
        "lookup",
        f"Which medications is this patient currently taking (as of {as_of.isoformat()})?",
        {"type": "set", "items": current},
        gold,
        True,
    )

    # conditions: current (yes) vs resolved (no) as of the last note
    last_current = [
        f
        for f in last.facts
        if f.fact_type == "condition" and f.polarity == "affirmed" and f.temporality == "current"
    ]
    last_hist = [
        f for f in last.facts if f.fact_type == "condition" and f.temporality == "historical"
    ]
    if last_current:
        f0 = rng.choice(last_current)
        q(
            "condition_current",
            "temporality",
            f"Does this patient currently have {f0.label.lower()}?",
            {"type": "yes_no", "value": True},
            fact_ids(
                [last],
                note_ids,
                lambda n, f: (
                    f.fact_type == "condition"
                    and f.concept_id == f0.concept_id
                    and f.temporality == "current"
                ),
            ),
            True,
            concept_id=f0.concept_id,
        )
    if last_hist:
        f0 = rng.choice(last_hist)
        q(
            "condition_historical",
            "temporality",
            f"Does this patient currently have {f0.label.lower()}?",
            {"type": "yes_no", "value": False},
            fact_ids(
                [last],
                note_ids,
                lambda n, f: (
                    f.fact_type == "condition"
                    and f.concept_id == f0.concept_id
                    and f.temporality == "historical"
                ),
            ),
            True,
            concept_id=f0.concept_id,
        )

    # negation trap: only ever written as "No evidence of X"
    written_neg = [
        (cid, name)
        for cid, name in plan.negation_targets
        if any(f.concept_id == cid and f.polarity == "negated" for n in notes for f in n.facts)
    ]
    if written_neg:
        cid, name = rng.choice(written_neg)
        q(
            "negation_trap",
            "negation",
            f"Does this patient have {name.lower()}?",
            {"type": "yes_no", "value": False},
            fact_ids(notes, note_ids, lambda n, f: f.concept_id == cid and f.polarity == "negated"),
            True,
            concept_id=cid,
        )

    # family history: a trap when the patient lacks the condition, and a note-only question
    own = {c.concept_id for c in p.conditions}
    family_only = [(rel, cid, name) for rel, cid, name in plan.family if cid not in own]
    if family_only:
        rel, cid, name = rng.choice(family_only)
        q(
            "family_trap",
            "family_history",
            f"Does this patient have {name.lower()}?",
            {"type": "yes_no", "value": False},
            fact_ids(
                notes,
                note_ids,
                lambda n, f: f.fact_type == "family_condition" and f.concept_id == cid,
            ),
            True,
            concept_id=cid,
        )
    if plan.family:
        rel, cid, name = rng.choice(plan.family)
        q(
            "family_history",
            "note_only",
            f"Is there a family history of {name.lower()}, and if so in which relative?",
            {"type": "yes_no", "value": True, "relative": rel},
            fact_ids(
                notes,
                note_ids,
                lambda n, f: (
                    f.fact_type == "family_condition" and f.concept_id == cid and f.value == rel
                ),
            ),
            False,
            concept_id=cid,
        )

    # why a drug was stopped: documented (note-only) or not documented (abstention)
    if plan.stop_reasons:
        ing_id = rng.choice(sorted(plan.stop_reasons))
        name, reason, stopped = plan.stop_reasons[ing_id]
        q(
            "stop_reason",
            "note_only",
            f"Why was {name} discontinued?",
            {"type": "text", "value": reason},
            fact_ids(
                notes,
                note_ids,
                lambda n, f: f.fact_type == "medication_stop_reason" and f.concept_id == ing_id,
            ),
            False,
            ingredient_id=ing_id,
        )
    if plan.stopped_unexplained:
        ing_id = rng.choice(sorted(plan.stopped_unexplained))
        name, _ = plan.stopped_unexplained[ing_id]
        q(
            "stop_reason_undocumented",
            "abstention",
            f"Why was {name} discontinued?",
            {"type": "not_documented"},
            [],
            False,
            ingredient_id=ing_id,
        )

    # a lab never measured for this patient, at any time in the notes
    measured = {lab.loinc for lab in p.labs}
    never = sorted(set(LABS) - measured)
    if never:
        loinc = rng.choice(never)
        q(
            "lab_not_documented",
            "abstention",
            f"What was this patient's most recent {LABS[loinc]} result, and on what date?",
            {"type": "not_documented"},
            [],
            True,
            loinc=loinc,
        )
    return out


def select(cands: dict[str, Question], person_id: int, n: int, seed: int) -> list[Question]:
    """All available core templates, then a seeded choice of optional ones, up to n."""
    chosen = [cands[t] for t in CORE if t in cands]
    optional = [cands[t] for t in OPTIONAL if t in cands]
    rng = rng_for(seed, person_id, "question-select")
    rng.shuffle(optional)
    chosen += optional[: max(0, n - len(chosen))]
    return sorted(chosen, key=lambda q: q.question_id)


def validate(questions: list[Question], facts_by_id: dict[str, Fact]) -> None:
    """Every answerable question must point at real supporting facts; abstentions at none."""
    for q in questions:
        if q.answer["type"] == "not_documented":
            assert not q.gold_fact_ids, q.question_id
        elif q.template != "current_medications" or q.answer["items"]:
            assert q.gold_fact_ids, f"{q.question_id}: no supporting fact in any note"
        missing = [fid for fid in q.gold_fact_ids if fid not in facts_by_id]
        assert not missing, f"{q.question_id}: unknown facts {missing}"
