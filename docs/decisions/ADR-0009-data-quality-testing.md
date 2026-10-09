# ADR-0009: Data-quality testing strategy

**Status:** accepted (Phase 2)

## Layers of tests
| What | How | Severity |
|---|---|---|
| Primary keys unique and not null; foreign keys to person and visit; every `*_concept_id` exists in `vocab.concept` | dbt generic tests (`unique`, `not_null`, `relationships`) | error |
| **Conformance to CDM v5.4**: same columns, same order, compatible types as the official field list | `tests/cdm_conforms_to_v54_spec.sql` against seed `cdm_v54_fields` (generated from OHDSI/CommonDataModel) | error |
| Every field the spec marks *required* is populated | `tests/cdm_required_fields_not_null.sql` (reads the spec seed at run time) | error |
| Hard-coded concept ids exist with the expected name | `tests/fixed_concept_ids_are_valid.sql` | error |
| Date logic and value plausibility | `dq_violations` model + `no_dq_violations` test per check | see below |
| Mapping coverage ≥ 95% of records per table | `dbt_utils.accepted_range` on `dq_mapping_coverage` | warn |
| **The checks themselves fire on bad data** | dbt **unit tests** feed fixed bad rows and assert the expected violations | error |

## Checks in `dq_violations`
- **error** (the ETL produced impossible data): event more than 60 days after death; event before birth; end before start; death before birth; observation period end before start.
- **warn** (known, documented properties of the *source*, reported with counts, not altered): event outside the observation period (23, see ADR-0008); measurement value outside physiological plausibility limits (1,390: HbA1c < 3% ×1,316 in 55 people, creatinine > 25 mg/dL ×70, LDL ×4).

**Why the checks are a model, not just tests.** A dbt data test can only say "this query returned rows". Making the checks a model means (1) **unit tests** can feed deliberately bad rows and prove each check fires, and (2) violations are a queryable table to triage, not a line in a log. Verified in both directions: breaking the drug end-date rule (`prescription_days: 31`) makes its unit test fail with a precise diff.

**Death grace window: 60 days**, the same as OHDSI DataQualityDashboard `plausibleBeforeDeath` (its SQL uses `DATEADD(day, 60, death_date)`). Every after-death record here is a "Death Certification" encounter or its cause-of-death observation, at most 14 days after death. A strict "nothing after death" rule would flag correct data.

**Plausibility ranges** (`seeds/measurement_plausible_ranges.csv`) are wide **physiological** limits, not reference ranges. They are judgement calls and listed explicitly so they can be reviewed. Values outside them are **reported, not altered**: an ETL that silently "fixes" source values hides problems from analysts.

## Not covered (limitations)
No checks on cross-table clinical plausibility (e.g. pregnancy codes in males), visit-type consistency, or temporal trends in data volume. The OHDSI DataQualityDashboard covers far more; running it against this CDM is a natural extension.
