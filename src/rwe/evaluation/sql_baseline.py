"""The plain-SQL baseline: one parameterised query per template, over the OMOP CDM (ADR-0015).

Each query uses the same definitions as the gold answers (notes window, the THEMIS drug
rule, "active on the as-of date"), so on structured questions this baseline is the
CEILING by construction, not an achievement; any disagreement with gold exposes a bug
in one of the two. Note-only templates (family history, stop reasons) have no SQL
answer: the CDM does not contain that information, and that is reported as N/A.
The answers are shaped like the LLM's, so the same grader scores both.
"""

from __future__ import annotations

import psycopg

from rwe.config import PipelineConfig

TYPE_PRESCRIPTION = 32838


def _yes_no(flag: bool) -> dict:
    return {
        "status": "answered",
        "yes_no": "yes" if flag else "no",
        "items": [],
        "explanation": "sql",
    }


def _not_documented() -> dict:
    return {
        "status": "not_documented",
        "yes_no": "not_applicable",
        "items": [],
        "explanation": "sql",
    }


def _value(value: str, day: str) -> dict:
    return {
        "status": "answered",
        "yes_no": "not_applicable",
        "items": [{"value": value, "date": day, "cited_chunks": []}],
        "explanation": "sql",
    }


def answer(conn: psycopg.Connection, cfg: PipelineConfig, q: dict) -> dict | None:
    """The SQL answer, or None when SQL cannot answer this template at all."""
    t, pid, params = q["template"], q["person_id"], q.get("params") or {}
    window, as_of = cfg.notes.window_start, q["as_of"]

    if t in ("latest_lab", "lab_not_documented"):
        row = conn.execute(
            """select m.value_as_number, m.measurement_date::text
               from cdm.measurement m
               join cdm.visit_occurrence v using (visit_occurrence_id)
               where m.person_id = %s and m.measurement_source_value = %s
                 and m.value_as_number is not null and v.visit_start_date >= %s
               order by m.measurement_date desc, m.measurement_id desc  -- last of the day
               limit 1""",
            (pid, params["loinc"], window),
        ).fetchone()
        return _value(f"{row[0]:g}", row[1]) if row else _not_documented()

    if t == "dx_date":
        row = conn.execute(
            """select min(condition_start_date)::text from cdm.condition_occurrence
               where person_id = %s and condition_concept_id = %s""",
            (pid, params["concept_id"]),
        ).fetchone()
        return _value(row[0], row[0]) if row and row[0] else _not_documented()

    if t == "current_medications":
        rows = conn.execute(
            """select distinct coalesce(lower(ing.names), lower(dc.concept_name))
               from cdm.drug_exposure de
               join vocab.concept dc on dc.concept_id = de.drug_concept_id
               left join lateral (
                   select string_agg(i.concept_name, ' / ' order by i.concept_name) as names
                   from vocab.concept_ancestor ca
                   join vocab.concept i on i.concept_id = ca.ancestor_concept_id
                    and i.concept_class_id = 'Ingredient' and i.standard_concept = 'S'
                   where ca.descendant_concept_id = de.drug_concept_id
               ) ing on true
               where de.person_id = %s and de.drug_type_concept_id = %s
                 and de.drug_concept_id <> 0
                 and %s::date between de.drug_exposure_start_date and de.drug_exposure_end_date""",
            (pid, TYPE_PRESCRIPTION, as_of),
        ).fetchall()
        return {
            "status": "answered",
            "yes_no": "not_applicable",
            "items": [{"value": r[0], "date": "", "cited_chunks": []} for r in rows],
            "explanation": "sql",
        }

    if t in ("condition_current", "condition_historical"):
        active = conn.execute(
            """select exists (select 1 from cdm.condition_occurrence
               where person_id = %s and condition_concept_id = %s
                 and condition_start_date <= %s::date
                 and (condition_end_date is null or condition_end_date > %s::date))""",
            (pid, params["concept_id"], as_of, as_of),
        ).fetchone()[0]
        return _yes_no(active)

    if t in ("negation_trap", "family_trap"):
        # "Does the patient have X?": any record of X or a descendant, at any time
        has = conn.execute(
            """select exists (select 1 from cdm.condition_occurrence co
               join vocab.concept_ancestor ca on ca.descendant_concept_id = co.condition_concept_id
               where co.person_id = %s and ca.ancestor_concept_id = %s)""",
            (pid, params["concept_id"]),
        ).fetchone()[0]
        return _yes_no(has)

    return None  # family_history, stop_reason, stop_reason_undocumented: not in the CDM
