"""Select evaluation patients and load what their notes are generated from: the CDM only.

Notes are built from OMOP tables (not FHIR), so every fact traces to a CDM row and the
SQL baseline in Phase 7 queries exactly the same data the notes were written from.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date

import psycopg

from rwe.config import PipelineConfig
from rwe.notes.model import Condition, DrugExposure, LabValue, Patient, Visit

TYPE_PRESCRIPTION = 32838
TYPE_ADMINISTRATION = 32818

# Labs and vitals that notes report and questions ask about (LOINC -> label used in text).
LABS = {
    "4548-4": "HbA1c",
    "2339-0": "blood glucose",
    "2093-3": "total cholesterol",
    "18262-6": "LDL cholesterol",
    "2085-9": "HDL cholesterol",
    "2571-8": "triglycerides",
    "38483-4": "creatinine",
    "33914-3": "eGFR",
    "6299-2": "urea nitrogen",
    "2947-0": "sodium",
    "6298-4": "potassium",
    "718-7": "hemoglobin",
    "29463-7": "body weight",
    "39156-5": "BMI",
    "8480-6": "systolic blood pressure",
    "8462-4": "diastolic blood pressure",
    "8867-4": "heart rate",
}


def eligible_pool(conn: psycopg.Connection, cfg: PipelineConfig) -> list[int]:
    rows = conn.execute(
        """
        select p.person_id
        from cdm.person p
        left join cdm.death d using (person_id)
        join cdm.visit_occurrence v using (person_id)
        where d.person_id is null
          and extract(year from age(%(as_of)s, p.birth_datetime)) >= %(min_age)s
        group by p.person_id
        having count(*) filter (where v.visit_start_date >= %(window)s) >= %(min_visits)s
           and count(*) <= %(max_visits)s
        order by p.person_id
        """,
        {
            "as_of": cfg.synthea.end_date,
            "min_age": cfg.eval.pool_min_age,
            "window": cfg.notes.window_start,
            "min_visits": cfg.eval.pool_min_visits_in_window,
            "max_visits": cfg.eval.pool_max_visits_total,
        },
    ).fetchall()
    return [r[0] for r in rows]


def sample_split(pool: list[int], cfg: PipelineConfig) -> dict[int, str]:
    """Seeded sample from the pool, split BY PATIENT so no patient's notes are in both sets."""
    wanted = cfg.eval.dev_patients + cfg.eval.test_patients
    if len(pool) < wanted:
        raise ValueError(f"Eligible pool has {len(pool)} patients; {wanted} requested")
    rng = random.Random(f"{cfg.seed}:eval-sample")
    chosen = rng.sample(sorted(pool), wanted)
    return {pid: ("dev" if i < cfg.eval.dev_patients else "test") for i, pid in enumerate(chosen)}


def _grouped(conn: psycopg.Connection, query: str, params: dict) -> dict[int, list[tuple]]:
    out: dict[int, list[tuple]] = defaultdict(list)
    for row in conn.execute(query, params).fetchall():
        out[row[0]].append(row[1:])
    return out


def load_patients(conn: psycopg.Connection, ids: list[int], window: date) -> list[Patient]:
    people = {
        r[0]: r[1:]
        for r in conn.execute(
            """select p.person_id, coalesce(g.concept_name, 'unknown'), p.birth_datetime::date
               from cdm.person p left join vocab.concept g on g.concept_id = p.gender_concept_id
               where p.person_id = any(%(ids)s)""",
            {"ids": ids},
        ).fetchall()
    }
    params = {"ids": ids, "window": window, "loincs": list(LABS)}
    visits = _grouped(
        conn,
        """
        select v.person_id, v.visit_occurrence_id, v.visit_start_date,
               replace(coalesce(c.concept_name, 'Visit'), ' Visit', '')
        from cdm.visit_occurrence v left join vocab.concept c on c.concept_id = v.visit_concept_id
        where v.person_id = any(%(ids)s) and v.visit_start_date >= %(window)s
        order by v.person_id, v.visit_start_date, v.visit_occurrence_id""",
        params,
    )
    conditions = _grouped(
        conn,
        """
        select co.person_id, co.condition_concept_id, c.concept_name, co.condition_start_date,
               co.condition_end_date, co.visit_occurrence_id
        from cdm.condition_occurrence co
        join vocab.concept c on c.concept_id = co.condition_concept_id
        where co.person_id = any(%(ids)s) and co.condition_concept_id <> 0
        order by co.person_id, co.condition_start_date, co.condition_occurrence_id""",
        params,
    )
    drugs = _grouped(
        conn,
        """
        select de.person_id, de.drug_type_concept_id, coalesce(ing.ids, de.drug_concept_id),
               coalesce(ing.names, dc.concept_name), dc.concept_name,
               de.drug_exposure_start_date, de.drug_exposure_end_date, de.visit_occurrence_id,
               dc.vocabulary_id
        from cdm.drug_exposure de
        join vocab.concept dc on dc.concept_id = de.drug_concept_id
        left join lateral (
            select min(i.concept_id) as ids,
                   string_agg(i.concept_name, ' / ' order by i.concept_name) as names
            from vocab.concept_ancestor ca
            join vocab.concept i on i.concept_id = ca.ancestor_concept_id
             and i.concept_class_id = 'Ingredient' and i.standard_concept = 'S'
            where ca.descendant_concept_id = de.drug_concept_id
        ) ing on true
        where de.person_id = any(%(ids)s) and de.drug_concept_id <> 0
        order by de.person_id, de.drug_exposure_start_date, de.drug_exposure_id""",
        params,
    )
    labs = _grouped(
        conn,
        """
        select m.person_id, m.measurement_source_value, m.value_as_number,
               coalesce(m.unit_source_value, ''), m.measurement_date, m.visit_occurrence_id
        from cdm.measurement m
        where m.person_id = any(%(ids)s) and m.value_as_number is not null
          and m.measurement_source_value = any(%(loincs)s)
          and m.measurement_date >= %(window)s
        order by m.person_id, m.measurement_date, m.measurement_id""",
        params,
    )

    patients = []
    for pid in sorted(ids):
        sex, birth = people[pid]
        prescriptions, immunizations = [], []
        for type_id, ing_id, ing, name, start, end, visit_id, vocab_id in drugs.get(pid, []):
            exposure = DrugExposure(ing_id, ing.lower(), name, start, end, visit_id)
            if vocab_id == "CVX":
                immunizations.append(exposure)
            elif type_id == TYPE_PRESCRIPTION:
                prescriptions.append(exposure)
        patient_visits = [Visit(*v) for v in visits.get(pid, [])]
        visit_ids = {v.visit_id for v in patient_visits}
        patients.append(
            Patient(
                person_id=pid,
                sex=sex.lower(),
                birth=birth,
                visits=patient_visits,
                conditions=[Condition(*c) for c in conditions.get(pid, [])],
                prescriptions=prescriptions,
                immunizations=immunizations,
                # only results attached to a noted visit: a value no note mentions can't be gold
                labs=[
                    LabValue(loinc, LABS[loinc], float(val), unit, day, vid)
                    for loinc, val, unit, day, vid in labs.get(pid, [])
                    if vid in visit_ids
                ],
            )
        )
    return patients


def trap_conditions(conn: psycopg.Connection) -> list[tuple[int, str, frozenset[int]]]:
    """Common chronic conditions usable as negation / family-history traps.

    Returns (concept_id, name, related concept ids). 'Related' = the concept with its
    ancestors and descendants, so "the patient does not have X" is checked against the
    whole hierarchy: a patient with type 2 diabetes is never told "no evidence of diabetes".
    """
    rows = conn.execute("""
        with chronic as (
            select condition_concept_id as concept_id
            from cdm.condition_occurrence
            where condition_concept_id <> 0
            group by 1
            having count(distinct person_id) >= 15
               and avg((condition_end_date is null)::int) >= 0.8
        )
        select c.concept_id, v.concept_name,
               array(select ca.descendant_concept_id from vocab.concept_ancestor ca
                     where ca.ancestor_concept_id = c.concept_id
                     union
                     select ca.ancestor_concept_id from vocab.concept_ancestor ca
                     where ca.descendant_concept_id = c.concept_id) as related
        from chronic c join vocab.concept v on v.concept_id = c.concept_id
        where v.domain_id = 'Condition'
        order by c.concept_id""").fetchall()
    return [(cid, name, frozenset(related) | {cid}) for cid, name, related in rows]
