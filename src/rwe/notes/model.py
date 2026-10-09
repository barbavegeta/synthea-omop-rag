"""Plain data types for notes and their ground truth (ADR-0011)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Condition:
    concept_id: int
    name: str
    start: date
    end: date | None
    visit_id: int | None

    def active_on(self, day: date) -> bool:
        return self.start <= day and (self.end is None or self.end > day)


@dataclass(frozen=True)
class DrugExposure:
    ingredient_id: int  # RxNorm ingredient (falls back to the drug concept)
    ingredient: str
    drug_name: str
    start: date
    end: date
    visit_id: int | None

    def active_on(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class LabValue:
    loinc: str
    label: str
    value: float
    unit: str
    day: date
    visit_id: int | None


@dataclass(frozen=True)
class Visit:
    visit_id: int
    day: date
    kind: str  # Outpatient / Emergency Room / Inpatient / Home / Telehealth


@dataclass
class Patient:
    person_id: int
    sex: str
    birth: date
    visits: list[Visit]
    conditions: list[Condition]
    prescriptions: list[DrugExposure]
    immunizations: list[DrugExposure]
    labs: list[LabValue]

    @property
    def as_of(self) -> date:
        """'Now' for this patient: the date of the last note."""
        return max(v.day for v in self.visits)


@dataclass(frozen=True)
class Fact:
    """One statement in a note, with where it is (character span) and what it means.

    polarity     affirmed | negated
    temporality  current | historical  (relative to the note's date)
    experiencer  patient | family
    source       cdm (derivable from structured data) | note_only (exists only in text)
    """

    fact_type: str
    label: str
    surface: str
    span_start: int
    span_end: int
    polarity: str = "affirmed"
    temporality: str = "current"
    experiencer: str = "patient"
    source: str = "cdm"
    concept_id: int | None = None
    value: str | None = None
    event_date: date | None = None
    abbreviated: bool = False


@dataclass
class Note:
    person_id: int
    visit_id: int
    day: date
    kind: str
    title: str
    text: str = ""
    facts: list[Fact] = field(default_factory=list)
