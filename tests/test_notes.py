import random
from datetime import date

import pytest

from rwe.config import load_config
from rwe.notes import pipeline, questions, render
from rwe.notes.model import Condition, DrugExposure, LabValue, Patient, Visit

CFG = load_config("default").notes
SEED = 1


def patient() -> Patient:
    return Patient(
        person_id=7,
        sex="female",
        birth=date(1960, 1, 1),
        visits=[
            Visit(1, date(2020, 1, 10), "Outpatient"),
            Visit(2, date(2021, 6, 1), "Outpatient"),
            Visit(3, date(2022, 3, 1), "Outpatient"),
        ],
        conditions=[
            Condition(201826, "Type 2 diabetes mellitus", date(2015, 5, 1), None, None),
            Condition(260139, "Acute bronchitis", date(2021, 6, 1), date(2021, 6, 20), 2),
        ],
        prescriptions=[
            DrugExposure(
                1503297, "metformin", "metformin 500 MG", date(2020, 1, 10), date(2020, 2, 8), 1
            ),
            DrugExposure(
                1503297, "metformin", "metformin 500 MG", date(2020, 2, 5), date(2020, 3, 5), None
            ),
            DrugExposure(
                1308216, "lisinopril", "lisinopril 10 MG", date(2022, 3, 1), date(2022, 3, 30), 3
            ),
        ],
        immunizations=[],
        labs=[
            LabValue("4548-4", "HbA1c", 7.1, "%", date(2020, 1, 10), 1),
            LabValue("4548-4", "HbA1c", 6.8, "%", date(2022, 3, 1), 3),
        ],
    )


TRAPS = [
    (201826, "Type 2 diabetes mellitus", frozenset({201826, 201820})),  # patient HAS this
    (201820, "Diabetes mellitus", frozenset({201820, 201826})),  # ancestor of what she has
    (316139, "Heart failure", frozenset({316139})),  # she does not have this
]


def test_note_builder_records_exact_spans():
    b = render.NoteBuilder()
    b.text("Denies ")
    b.fact("chest pain", fact_type="symptom", label="chest pain", polarity="negated")
    b.text(".")
    text, f = b.build(), b.facts[0]
    assert text[f.span_start : f.span_end] == "chest pain"


def test_abbreviation_is_rate_controlled():
    rng = random.Random(0)
    assert render.abbreviate("Type 2 diabetes mellitus", rng, 1.0) == ("T2DM", True)
    assert render.abbreviate("Essential hypertension", rng, 0.0) == (
        "Essential hypertension",
        False,
    )
    assert render.abbreviate("Chronic kidney disease stage 2", rng, 1.0) == ("CKD stage 2", True)


def test_negation_targets_respect_the_concept_hierarchy():
    plan = render.plan_patient(patient(), TRAPS, CFG, SEED)
    # never "no evidence of diabetes" for a patient with type 2 diabetes
    assert [cid for cid, _ in plan.negation_targets] == [316139]


def test_stop_reasons_are_plausible_for_the_drug():
    rng = random.Random(0)
    assert render.stop_reason("lisinopril", 5, rng) == "persistent dry cough"
    assert render.stop_reason("amoxicillin", 1, rng) == render.COURSE_COMPLETED
    assert render.stop_reason("galantamine", 4, rng) in render.GENERIC_STOP_REASONS


def test_rendering_is_deterministic_and_spans_hold():
    notes_a, _ = render.render_patient(patient(), TRAPS, CFG, SEED)
    notes_b, _ = render.render_patient(patient(), TRAPS, CFG, SEED)
    assert [n.text for n in notes_a] == [n.text for n in notes_b]
    for note in notes_a:
        for f in note.facts:
            assert note.text[f.span_start : f.span_end] == f.surface


def test_resolved_condition_is_written_as_history():
    notes, _ = render.render_patient(patient(), TRAPS, CFG, SEED)
    last = notes[-1]
    bronchitis = [f for f in last.facts if f.concept_id == 260139]
    assert bronchitis and all(f.temporality == "historical" for f in bronchitis)
    assert "resolved 2021-06-20" in last.text


def generated():
    p = patient()
    notes, plan = render.render_patient(p, TRAPS, CFG, SEED)
    note_ids = {n.visit_id: i + 1 for i, n in enumerate(notes)}
    cands = questions.candidates(p, notes, plan, note_ids, SEED)
    facts = {
        questions.fact_id(note_ids[n.visit_id], k): f for n in notes for k, f in enumerate(n.facts)
    }
    return p, cands, facts


def test_questions_have_consistent_gold():
    p, cands, facts = generated()
    qs = list(cands.values())
    questions.validate(qs, facts)
    latest = cands["latest_lab"]
    assert latest.answer == {"type": "lab", "value": 6.8, "unit": "%", "date": "2022-03-01"}
    assert cands["current_medications"].answer == {"type": "set", "items": ["lisinopril"]}
    assert cands["condition_historical"].answer["value"] is False
    assert cands["lab_not_documented"].gold_fact_ids == []


def test_selection_is_core_first_and_capped():
    p, cands, _ = generated()
    chosen = questions.select(cands, p.person_id, 6, SEED)
    templates = {q.template for q in chosen}
    assert len(chosen) == min(6, len(cands))
    assert {t for t in questions.CORE if t in cands} <= templates


def test_test_set_freeze(tmp_path):
    p, cands, _ = generated()
    qs = list(cands.values())
    split = {p.person_id: "test"}
    first = pipeline.write_files(tmp_path, split, qs)
    assert pipeline.write_files(tmp_path, split, qs)["test_sha256"] == first["test_sha256"]
    changed = qs[1:]
    with pytest.raises(pipeline.FrozenTestSetError):
        pipeline.write_files(tmp_path, split, changed)
    assert (
        pipeline.write_files(tmp_path, split, changed, refreeze=True)["test_sha256"]
        != first["test_sha256"]
    )
