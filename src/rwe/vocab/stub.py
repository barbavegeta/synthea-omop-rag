"""Synthetic vocabulary for CI, built from the codes present in the loaded FHIR data.

CI cannot use Athena: the content is licensed (SNOMED, LOINC, ...) and multi-GB. The stub
reproduces the *structure* the ETL relies on, not the content:

* every source code gets a concept in the OMOP local range (id > 2,000,000,000, which
  OMOP reserves for site-defined concepts), named with Synthea's own display text;
* each is standard with a 'Maps to' itself, and a domain guessed from its FHIR resource;
* CDT codes are left out on purpose, so CI still exercises the unmapped path;
* the handful of OMOP-authored concepts the ETL references by id (gender, race,
  ethnicity, visit, type concepts) are included with their real ids and names.

Mapping-coverage numbers from a stub build mean nothing; real coverage comes from Athena.
"""

from __future__ import annotations

import csv
from datetime import date

import psycopg

from rwe.config import REPO_ROOT
from rwe.vocab.load_athena import INDEXES, TABLES

LOCAL_ID_START = 2_000_000_001
VALID_FROM, VALID_TO = date(1970, 1, 1), date(2099, 12, 31)
SEED = REPO_ROOT / "dbt" / "seeds" / "fhir_code_systems.csv"
EXCLUDED_VOCABULARIES = {"CDT"}  # licensed in real life: stays unmapped in the stub too

# (concept_id, name, domain, vocabulary, class, code)
OMOP_FIXED = [
    (8507, "MALE", "Gender", "Gender", "Gender", "M"),
    (8532, "FEMALE", "Gender", "Gender", "Gender", "F"),
    (8527, "White", "Race", "Race", "Race", "5"),
    (8516, "Black or African American", "Race", "Race", "Race", "3"),
    (8515, "Asian", "Race", "Race", "Race", "2"),
    (8557, "Native Hawaiian or Other Pacific Islander", "Race", "Race", "Race", "4"),
    (8657, "American Indian or Alaska Native", "Race", "Race", "Race", "1"),
    (38003563, "Hispanic or Latino", "Ethnicity", "Ethnicity", "Ethnicity", "Hispanic"),
    (38003564, "Not Hispanic or Latino", "Ethnicity", "Ethnicity", "Ethnicity", "Not Hispanic"),
    (9201, "Inpatient Visit", "Visit", "Visit", "Visit", "IP"),
    (9202, "Outpatient Visit", "Visit", "Visit", "Visit", "OP"),
    (9203, "Emergency Room Visit", "Visit", "Visit", "Visit", "ER"),
    (581476, "Home Visit", "Visit", "Visit", "Visit", "OMOP4822459"),
    (722455, "Telehealth", "Visit", "Visit", "Visit", "OMOP5556618"),
    (32817, "EHR", "Type Concept", "Type Concept", "Type Concept", "stub"),
    (
        32818,
        "EHR administration record",
        "Type Concept",
        "Type Concept",
        "Type Concept",
        "stub",
    ),
    (32838, "EHR prescription", "Type Concept", "Type Concept", "Type Concept", "stub"),
    (32831, "EHR note", "Type Concept", "Type Concept", "Type Concept", "stub"),
    (32834, "EHR outpatient note", "Type Concept", "Type Concept", "Type Concept", "stub"),
    (32826, "EHR emergency room note", "Type Concept", "Type Concept", "Type Concept", "stub"),
    (32829, "EHR inpatient note", "Type Concept", "Type Concept", "Type Concept", "stub"),
    (3000735, "Progress note", "Note", "LOINC", "Clinical Observation", "11506-3"),
    (32678, "UTF-8", "Metadata", "Metadata", "Encoding", "stub"),
    (4180186, "English language", "Language", "SNOMED", "Qualifier Value", "297496007"),
]

# Every coding anywhere in a resource, plus quantity units, with the resource it came from.
SOURCE_CODES_SQL = """
    select distinct on (system, code) system, code, display, resource_type
    from (
        select c ->> 'system' as system, c ->> 'code' as code, c ->> 'display' as display,
               resource_type
        from raw.fhir_resource, jsonb_path_query(payload, 'lax $.**.coding[*]') c
        union all
        select q ->> 'system', q ->> 'code', q ->> 'unit', resource_type
        from raw.fhir_resource, jsonb_path_query(payload, 'lax $.**.valueQuantity') q
    ) x
    where system is not null and code is not null
    order by system, code, resource_type
"""


def code_systems() -> dict[str, str]:
    with SEED.open(newline="") as fh:
        return {row["fhir_system"]: row["vocabulary_id"] for row in csv.DictReader(fh)}


def guess_domain(vocabulary_id: str, resource_type: str) -> str:
    if vocabulary_id in ("RxNorm", "CVX"):
        return "Drug"
    if vocabulary_id == "UCUM":
        return "Unit"
    if vocabulary_id == "LOINC":
        return "Measurement"
    return {"Condition": "Condition", "Procedure": "Procedure"}.get(resource_type, "Observation")


def build_rows(source_codes: list[tuple[str, str, str, str]]) -> list[tuple]:
    systems = code_systems()
    rows = [(*fixed, "S") for fixed in OMOP_FIXED]
    next_id = LOCAL_ID_START
    for system, code, display, resource_type in source_codes:
        vocabulary_id = systems.get(system)
        if vocabulary_id is None or vocabulary_id in EXCLUDED_VOCABULARIES:
            continue
        name = (display or code)[:255]
        domain = guess_domain(vocabulary_id, resource_type)
        rows.append((next_id, name, domain, vocabulary_id, "Stub", code, "S"))
        next_id += 1
    return rows


def load(conn: psycopg.Connection) -> dict:
    source_codes = conn.execute(SOURCE_CODES_SQL).fetchall()
    concepts = build_rows(source_codes)
    vocabularies = sorted({c[3] for c in concepts})
    with conn.transaction():
        for table, columns in TABLES.items():
            conn.execute(f"DROP TABLE IF EXISTS vocab.{table}")
            conn.execute(f"CREATE TABLE vocab.{table} ({columns})")
        with conn.cursor().copy("COPY vocab.concept FROM STDIN") as copy:
            copy.write_row(
                (
                    0,
                    "No matching concept",
                    "Metadata",
                    "None",
                    "Undefined",
                    None,
                    "No matching concept",
                    VALID_FROM,
                    VALID_TO,
                    None,
                )
            )
            for cid, name, domain, vocab, cls, code, std in concepts:
                copy.write_row(
                    (cid, name, domain, vocab, cls, std, code, VALID_FROM, VALID_TO, None)
                )
        with conn.cursor().copy("COPY vocab.concept_relationship FROM STDIN") as copy:
            for cid, *_ in concepts:
                copy.write_row((cid, cid, "Maps to", VALID_FROM, VALID_TO, None))
        with conn.cursor().copy("COPY vocab.concept_ancestor FROM STDIN") as copy:
            for cid, *_ in concepts:
                copy.write_row((cid, cid, 0, 0))
        with conn.cursor().copy("COPY vocab.vocabulary FROM STDIN") as copy:
            copy.write_row(
                (
                    "None",
                    "OMOP Standardized Vocabularies",
                    None,
                    "STUB - synthetic, CI only",
                    44819096,
                )
            )
            for vocab in vocabularies:
                copy.write_row((vocab, f"{vocab} (stub)", None, "stub", 0))
        for statement in INDEXES:
            conn.execute(statement)
        conn.execute("CREATE TABLE IF NOT EXISTS vocab.load_info (signature text NOT NULL)")
        conn.execute("DELETE FROM vocab.load_info")
        conn.execute("INSERT INTO vocab.load_info VALUES ('stub')")
    conn.commit()
    return {"release": "STUB - synthetic, CI only", "concepts": len(concepts) + 1}
