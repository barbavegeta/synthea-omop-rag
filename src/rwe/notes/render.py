"""Deterministic note templates with planted, labelled phenomena (ADR-0011).

Every statement of fact is written through NoteBuilder.fact(), which records its exact
character span. Ground truth is therefore exact by construction, and Phase 5/7 can tell
precisely which chunk contains which fact.

Planted phenomena, each labelled on the Fact:
  negation      ROS "Denies ..." (symptoms) and "No evidence of <condition>" (conditions the
                patient never has, checked across the whole concept hierarchy)
  temporality   past medical history marks resolved conditions "h/o ... resolved <date>";
                medications list "Previously: ..." with the last prescription date
  experiencer   family history (mother/father/sibling), including conditions the patient lacks
  abbreviation  HTN, T2DM, HLD, SOB, ... at a configured rate
  note-only     drug stop reasons (clinically plausible per drug), family history and
                symptoms exist only in the text
All randomness comes from random.Random seeded with (global seed, person, purpose), so a
patient's notes do not change when other patients are added or removed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from rwe.config import NotesConfig
from rwe.notes.model import Condition, DrugExposure, Fact, Note, Patient

ABBREVIATIONS = {
    "essential hypertension": "HTN",
    "hypertensive disorder": "HTN",
    "type 2 diabetes mellitus": "T2DM",
    "hyperlipidemia": "HLD",
    "chronic kidney disease": "CKD",
    "coronary arteriosclerosis": "CAD",
    "ischemic heart disease": "IHD",
    "myocardial infarction": "MI",
    "chronic obstructive lung disease": "COPD",
    "atrial fibrillation": "AF",
    "shortness of breath": "SOB",
    "chest pain": "CP",
    "systolic blood pressure": "SBP",
    "diastolic blood pressure": "DBP",
    "heart rate": "HR",
    "blood glucose": "BG",
    "body weight": "wt",
}

SYMPTOMS = [
    "chest pain",
    "shortness of breath",
    "fever",
    "cough",
    "abdominal pain",
    "nausea",
    "headache",
    "dizziness",
    "palpitations",
    "leg swelling",
    "blurred vision",
    "joint pain",
    "fatigue",
    "weight loss",
]

# Stop reasons must be clinically plausible for the drug: a reviewer would rightly object
# to "cough syrup stopped due to dry cough". Known class effects first; one-off
# prescriptions end because the course finished; anything else gets a generic reason.
CLASS_STOP_REASONS = {
    "lisinopril": "persistent dry cough",
    "metformin": "gastrointestinal intolerance",
    "simvastatin": "muscle aches",
    "atorvastatin": "muscle aches",
    "amlodipine": "ankle swelling",
    "hydrochlorothiazide": "dizziness on standing",
    "nitroglycerin": "headaches",
    "clopidogrel": "easy bruising",
}
COURSE_COMPLETED = "the course being completed"
GENERIC_STOP_REASONS = ["patient preference", "cost concerns raised by the patient", "a rash"]


def stop_reason(ingredient: str, prescriptions: int, rng: random.Random) -> str:
    if ingredient in CLASS_STOP_REASONS:
        return CLASS_STOP_REASONS[ingredient]
    if prescriptions == 1:
        return COURSE_COMPLETED
    return rng.choice(GENERIC_STOP_REASONS)


RELATIVES = ["mother", "father", "sister", "brother"]


def rng_for(seed: int, person_id: int, purpose: str) -> random.Random:
    return random.Random(f"{seed}:{person_id}:{purpose}")


def abbreviate(term: str, rng: random.Random, rate: float) -> tuple[str, bool]:
    """Return (surface form, abbreviated?). Matches a known prefix, case-insensitively."""
    lower = term.lower()
    for full, short in ABBREVIATIONS.items():
        if lower.startswith(full) and rng.random() < rate:
            return short + term[len(full) :], True
    return term, False


class NoteBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.facts: list[Fact] = []

    def text(self, s: str) -> None:
        self.parts.append(s)
        self.length += len(s)

    def fact(self, surface: str, **attrs) -> None:
        self.facts.append(
            Fact(
                surface=surface,
                span_start=self.length,
                span_end=self.length + len(surface),
                **attrs,
            )
        )
        self.text(surface)

    def build(self) -> str:
        return "".join(self.parts)


@dataclass
class PatientPlan:
    """Patient-level planted content, needed later to write questions and gold answers."""

    family: list[tuple[str, int, str]] = field(default_factory=list)  # relative, concept, name
    negation_targets: list[tuple[int, str]] = field(default_factory=list)
    stop_reasons: dict[int, tuple[str, str, date]] = field(
        default_factory=dict
    )  # ing -> name, reason, date
    stopped_unexplained: dict[int, tuple[str, date]] = field(default_factory=dict)


def plan_patient(
    p: Patient, traps: list[tuple[int, str, frozenset[int]]], cfg: NotesConfig, seed: int
) -> PatientPlan:
    plan = PatientPlan()
    own = {c.concept_id for c in p.conditions}
    absent = [(cid, name) for cid, name, related in traps if not (related & own)]

    fam_rng = rng_for(seed, p.person_id, "family")
    for relative in fam_rng.sample(RELATIVES, k=fam_rng.randint(1, 3)):
        cid, name, _ = fam_rng.choice(traps) if traps else (0, "", frozenset())
        if cid:
            plan.family.append((relative, cid, name))

    neg_rng = rng_for(seed, p.person_id, "negation")
    plan.negation_targets = neg_rng.sample(absent, k=min(2, len(absent)))

    stop_rng = rng_for(seed, p.person_id, "stop")
    last_end: dict[int, tuple[str, date]] = {}
    n_prescriptions: dict[int, int] = {}
    for e in p.prescriptions:
        n_prescriptions[e.ingredient_id] = n_prescriptions.get(e.ingredient_id, 0) + 1
        if e.ingredient_id not in last_end or e.end > last_end[e.ingredient_id][1]:
            last_end[e.ingredient_id] = (e.ingredient, e.end)
    first_note = min(v.day for v in p.visits)
    for ing_id in sorted(last_end):
        name, end = last_end[ing_id]
        # stopped: last exposure ended before the final note, inside the notes window
        if not (first_note <= end < p.as_of):
            continue
        if stop_rng.random() < cfg.stop_reason_rate:
            reason = stop_reason(name, n_prescriptions[ing_id], stop_rng)
            plan.stop_reasons[ing_id] = (name, reason, end)
        else:
            plan.stopped_unexplained[ing_id] = (name, end)
    return plan


def _condition_lines(
    b: NoteBuilder, p: Patient, day: date, rng: random.Random, rate: float
) -> None:
    """Past medical history as of `day`: active conditions, then recently resolved ones."""
    first_start: dict[int, Condition] = {}
    for c in p.conditions:
        if c.start <= day and (
            c.concept_id not in first_start or c.start < first_start[c.concept_id].start
        ):
            first_start[c.concept_id] = c
    active = sorted(
        {c.concept_id for c in p.conditions if c.active_on(day)},
        key=lambda cid: first_start[cid].start,
    )
    resolved = {}
    for c in p.conditions:  # latest resolved episode per concept, within 3 years
        recently_resolved = (
            c.end is not None
            and day - timedelta(days=3 * 365) <= c.end <= day
            and c.concept_id not in active
        )
        if recently_resolved and (
            c.concept_id not in resolved or c.end > resolved[c.concept_id].end
        ):
            resolved[c.concept_id] = c
    b.text("PAST MEDICAL HISTORY\n")
    if not active and not resolved:
        b.text("No significant past medical history.\n")
    for cid in active:
        c = first_start[cid]
        surface, abbr = abbreviate(c.name, rng, rate)
        b.text("- ")
        b.fact(
            surface,
            fact_type="condition",
            label=c.name,
            concept_id=cid,
            event_date=c.start,
            abbreviated=abbr,
        )
        b.text(f", diagnosed {c.start.isoformat()}\n")
    for cid, c in sorted(resolved.items(), key=lambda kv: kv[1].end):
        surface, abbr = abbreviate(c.name, rng, rate)
        prefix = "h/o " if rng.random() < rate else "history of "
        b.text("- ")
        b.fact(
            f"{prefix}{surface}",
            fact_type="condition",
            label=c.name,
            concept_id=cid,
            temporality="historical",
            event_date=c.start,
            abbreviated=abbr or prefix == "h/o ",
        )
        b.text(f", resolved {c.end.isoformat()}\n")


def render_note(
    p: Patient, visit_index: int, plan: PatientPlan, cfg: NotesConfig, seed: int
) -> Note:
    visit = p.visits[visit_index]
    day = visit.day
    rng = rng_for(seed, p.person_id, f"note:{visit.visit_id}")
    rate = cfg.abbreviation_rate
    b = NoteBuilder()
    title = f"{visit.kind} note"
    b.text(f"{title.upper()}\nDate: {day.isoformat()}\nPatient: {p.sex}, born {p.birth.year}\n\n")

    _condition_lines(b, p, day, rng, rate)

    first_note = visit_index == 0
    if plan.family and (first_note or rng.random() < cfg.family_history_rate):
        b.text("\nFAMILY HISTORY\n")
        for relative, cid, name in plan.family:
            surface, abbr = abbreviate(name, rng, rate)
            b.text(f"{relative.capitalize()}: ")
            b.fact(
                surface,
                fact_type="family_condition",
                label=name,
                concept_id=cid,
                experiencer="family",
                source="note_only",
                value=relative,
                abbreviated=abbr,
            )
            b.text(".\n")

    b.text("\nMEDICATIONS\n")
    current = {}
    for e in p.prescriptions:
        if e.active_on(day):
            current.setdefault(e.ingredient_id, e)
    if current:
        b.text("Current: ")
        for i, (ing_id, e) in enumerate(sorted(current.items(), key=lambda kv: kv[1].ingredient)):
            if i:
                b.text("; ")
            b.fact(
                e.ingredient,
                fact_type="medication_current",
                label=e.ingredient,
                concept_id=ing_id,
                event_date=e.start,
            )
            b.text(f" ({e.drug_name})")
        b.text(".\n")
    else:
        b.fact("Current: no active prescriptions", fact_type="medication_none", label="none")
        b.text(".\n")
    previous: dict[int, DrugExposure] = {}
    for e in p.prescriptions:
        ended_recently = (
            e.ingredient_id not in current
            and e.start <= day
            and day - timedelta(days=730) <= e.end < day
        )
        if ended_recently and (
            e.ingredient_id not in previous or e.start > previous[e.ingredient_id].start
        ):
            previous[e.ingredient_id] = e
    if previous:
        b.text("Previously: ")
        for i, (ing_id, e) in enumerate(sorted(previous.items(), key=lambda kv: kv[1].ingredient)):
            if i:
                b.text("; ")
            b.fact(
                e.ingredient,
                fact_type="medication_previous",
                label=e.ingredient,
                concept_id=ing_id,
                temporality="historical",
                event_date=e.start,
            )
            b.text(f" (last prescribed {e.start.isoformat()})")
        b.text(".\n")

    own_names = " ".join(c.name.lower() for c in p.conditions if c.active_on(day))
    symptoms = [s for s in SYMPTOMS if s.split()[0] not in own_names]
    b.text("\nREVIEW OF SYSTEMS\nDenies ")
    for i, s in enumerate(rng.sample(symptoms, k=min(3, len(symptoms)))):
        if i:
            b.text(", ")
        surface, abbr = abbreviate(s, rng, rate)
        b.fact(
            surface,
            fact_type="symptom",
            label=s,
            polarity="negated",
            source="note_only",
            abbreviated=abbr,
        )
    b.text(".\n")

    labs = {}
    for lab in p.labs:
        if lab.visit_id == visit.visit_id:
            labs[lab.loinc] = lab  # last value of each test at this visit
    shots = sorted({e.ingredient for e in p.immunizations if e.visit_id == visit.visit_id})
    if labs or shots:
        b.text("\nOBJECTIVE\n")
        for i, lab in enumerate(sorted(labs.values(), key=lambda x: x.label)):
            if i:
                b.text("; ")
            surface, abbr = abbreviate(lab.label, rng, rate)
            text = f"{surface} {lab.value:g} {lab.unit}".rstrip()
            b.fact(
                text,
                fact_type="lab_value",
                label=lab.label,
                value=f"{lab.value:g}",
                event_date=lab.day,
                abbreviated=abbr,
            )
        if labs:
            b.text(".\n")
        if shots:
            b.text("Immunizations given: ")
            for i, s in enumerate(shots):
                if i:
                    b.text(", ")
                b.fact(s, fact_type="immunization", label=s, event_date=day)
            b.text(".\n")

    b.text("\nASSESSMENT AND PLAN\n")
    wrote_plan = False
    for c in sorted(
        (c for c in p.conditions if c.visit_id == visit.visit_id), key=lambda c: c.name
    ):
        surface, abbr = abbreviate(c.name, rng, rate)
        b.text("New diagnosis: ")
        b.fact(
            surface,
            fact_type="condition",
            label=c.name,
            concept_id=c.concept_id,
            event_date=c.start,
            abbreviated=abbr,
        )
        b.text(".\n")
        wrote_plan = True
    started = {}
    for e in p.prescriptions:
        if e.start == day and not any(
            o.ingredient_id == e.ingredient_id and o.active_on(day - timedelta(days=1))
            for o in p.prescriptions
        ):
            started.setdefault(e.ingredient_id, e)
    for ing_id, e in sorted(started.items(), key=lambda kv: kv[1].ingredient):
        b.text("Started ")
        b.fact(
            e.ingredient,
            fact_type="medication_started",
            label=e.ingredient,
            concept_id=ing_id,
            event_date=day,
        )
        b.text(f" ({e.drug_name}).\n")
        wrote_plan = True
    previous_day = p.visits[visit_index - 1].day if visit_index else date.min
    for ing_id, (name, reason, stopped) in sorted(plan.stop_reasons.items()):
        if previous_day <= stopped < day:  # first note after the stop
            b.text(f"{name.capitalize()} was discontinued after {stopped.isoformat()} due to ")
            b.fact(
                reason,
                fact_type="medication_stop_reason",
                label=name,
                concept_id=ing_id,
                source="note_only",
                value=reason,
                event_date=stopped,
                temporality="historical",
            )
            b.text(".\n")
            wrote_plan = True
    if plan.negation_targets and rng.random() < cfg.no_evidence_rate:
        cid, name = rng.choice(plan.negation_targets)
        surface, abbr = abbreviate(name, rng, rate)
        b.text("No evidence of ")
        b.fact(
            surface,
            fact_type="condition",
            label=name,
            concept_id=cid,
            polarity="negated",
            abbreviated=abbr,
        )
        b.text(".\n")
        wrote_plan = True
    if not wrote_plan:
        b.text("Stable. Continue current management.\n")

    return Note(
        person_id=p.person_id,
        visit_id=visit.visit_id,
        day=day,
        kind=visit.kind,
        title=title,
        text=b.build(),
        facts=b.facts,
    )


def render_patient(
    p: Patient, traps: list[tuple[int, str, frozenset[int]]], cfg: NotesConfig, seed: int
) -> tuple[list[Note], PatientPlan]:
    plan = plan_patient(p, traps, cfg, seed)
    notes = [render_note(p, i, plan, cfg, seed) for i in range(len(p.visits))]
    return notes, plan
