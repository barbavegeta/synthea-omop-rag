# ADR-0006: Concept mapping, domain routing and the dbt layering

**Status:** accepted (Phase 2)

## Context
OMOP analyses run on **standard concepts**: one agreed concept per clinical idea, so a cohort definition works across databases that coded the same thing differently. Source codes (SNOMED, LOINC, RxNorm, CVX, ICD-10-CM, CDT) must be mapped to standard concepts with the OHDSI vocabularies. The **domain** of the standard concept (Condition, Drug, Measurement, ...) decides which CDM table a record belongs to.

## Decisions

**Layering.**
- `stg`: one model per FHIR resource, typed field extraction only.
- `int`: integer ids, one shared mapping engine, routing.
- `cdm`: the tables, each selecting its domain.
- `dq`: findings.

Every coded event, whatever its FHIR resource, goes through **one** mapping path (`int_events` → `int_events_mapped`), so the mapping rules exist exactly once.

**Mapping path:** FHIR system URL → `vocabulary_id` (seed `fhir_code_systems`) → `vocab.concept` on (vocabulary_id, concept_code) → `concept_relationship` 'Maps to' (valid only) → standard (`standard_concept = 'S'`, valid) target.
- It is done **once per distinct code** (`int_concept_map`, about 1,850 codes), then joined to about 1.1M events.
- `mapping_status` records *why* each unmapped code is 0: `unknown_code_system`, `code_not_in_vocabulary` or `no_standard_mapping`.

**Domain routing:** the CDM table comes from the standard concept's domain, **not** the FHIR resource type. On the full population:
- 21,693 FHIR Conditions are Observation-domain (social findings such as employment);
- 43,445 FHIR Procedures are Measurement-domain (screenings and assessments).

Unmapped events keep `concept_id = 0` and fall back to the domain their resource implies. They stay visible in the CDM and in coverage metrics instead of vanishing. Domains without a table in this subset (Note, Device: 212 records) are **counted as dropped** in `dq_mapping_coverage`.

**Multiple codings:** 5,300 observations carry two codings. Use the first coding that maps to a standard concept, else the first coding.

**One-to-many maps:** one CDM record per standard target (OMOP convention). This affects 7 codes.

**Source values are kept:** `*_source_value` holds the original code and `*_source_concept_id` the source concept, so every mapping can be audited.

**Demographic and visit crosswalks are explicit seeds** (race/ethnicity, gender, encounter class → Visit). Concepts are resolved by (vocabulary, code) at run time, never by hard-coded id.
- **Why race needs one:** Synthea's CDC race codes (e.g. `2106-3`, White) are not in the OHDSI Race vocabulary, and the same strings exist as unrelated **LOINC** codes (`2106-3` is a urine hCG test). A lookup on code alone would be silently wrong.

**Integer keys:** dense `row_number()` over the sorted FHIR UUIDs: deterministic for a given input. The FHIR id is kept in `person_source_value`.

## Results (Athena v5.0 29-AUG-26, 1,151 patients)
| CDM table | % records mapped | % distinct codes mapped |
|---|---|---|
| measurement | 99.99 | 98.1 |
| observation | 99.93 | 91.6 |
| drug_exposure | 100.00 | 100.0 |
| condition_occurrence | 99.00 | 98.2 |
| procedure_occurrence | **87.28** | **40.7** |

Procedures are low because of **CDT dental codes**. CDT is ADA-licensed and not distributable through Athena, so this is a licensing gap, not an ETL bug. The coverage test is set to *warn* below 95%, and it does warn. `dq_unmapped_codes` lists every unmapped code with its count and reason.

## Consequences / limitations
- 'Maps to value' relationships (codes whose meaning is split into concept + value) are not applied.
- Coverage numbers from CI use a synthetic stub vocabulary and are meaningless. Only Athena runs are reported.
