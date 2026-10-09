# ADR-0010: Type 2 diabetes cohort analysis (Phase 3)

**Status:** accepted. Design choices made by the project owner after reviewing feasibility counts.

## Context
The brief asked for a small RWE-style analysis on the CDM: a type 2 diabetes cohort, metformin exposure, HbA1c over time and a characterisation table. A feasibility check on the CDM changed the design:
- **78** people have a T2DM record, but their first records run from **1943 to 2025**. Synthea keeps an old diagnosis while it's active and drops the surrounding encounters (ADR-0005). For **59 of 78**, "first diagnosis" has no observed history before it, so an index date there is an artefact.
- **Synthea's HbA1c is not physiological.** In this cohort it rises to the diabetic range around diagnosis (baseline median 7.0%). But the whole-population median is about 4% for people with *and* without T2DM, values drift below 3% over long follow-up, and they move in smooth monotone steps whatever the treatment.

## Decisions
| Choice | Decision | Alternatives considered |
|---|---|---|
| Design | **Incident T2DM**: first-ever T2DM record (concept set with descendants) as index; index in observation period; age ≥ 18; **≥ 1 visit in the 365 days before index** (an *observed* look-back); no T1DM on or before index; exit at end of observation or death. **n = 19.** | Prevalent T2DM (n = 78, index dates mostly unobserved); new metformin users (n = 21; only 2 with HbA1c before and after) |
| Implausible HbA1c (< 3%) | **Excluded in the primary analysis; kept in a sensitivity analysis.** Same plausibility rule as Phase 2 data quality. | Include all values |
| Population | **Kept at 1,000.** A larger n would make the tables less sparse but no result more meaningful. | Regenerate about 5,000 |
| Covariate windows | Conditions: any time on or before index (chronic conditions are recorded once at onset). Drugs: 365 days before index. BMI and HbA1c: last value in 365 days before index. | Fixed 365-day window for everything |
| Drug exposure | OHDSI DRUG_ERA rule (gaps ≤ 30 days merge), on top of the 30-day prescription convention (ADR-0007). Unit-tested. | Raw exposure counts only |
| HbA1c summary | Per window: per-person mean, then median [IQR] across persons. A person with many values doesn't dominate. | Pooling all values |
| Analysis horizon | **5 years after index, decided *after* looking at the data** (some follow-up runs to about 48 years with sparse values, and an open last window made the plot imply a 35-year trend). The >5-year row is reported but not interpreted. Stated as post-hoc in the report. | Open-ended last window |
| Disclosure control | Counts 1–4 shown as `<5`; statistics hidden when fewer than 5 people contribute. Config `analysis.min_cell_count`. **Primary suppression only**: complementary cells can sometimes reveal a suppressed one; this is stated as a limitation. | No suppression (the data are synthetic); full complementary suppression |

## Implementation
- Cohort logic and features are SQL on the CDM: dbt models in the `results` schema, plus OHDSI-format `cohort` and `cohort_definition` tables. Concept sets are a reviewable seed (`concept_sets.csv`, vocabulary code + include-descendants), expanded through CONCEPT_ANCESTOR the way ATLAS does it.
- A test checks every concept-set code resolves in the vocabulary.
- Python (`rwe analyse`) only summarises, suppresses, plots and writes `analysis/t2dm_metformin/outputs/`. The outputs are deterministic: no timestamps.

## What the analysis can and cannot claim
It demonstrates the method. It supports **no** statement about glycaemic control or metformin effect: any before/after pattern would recover Synthea's disease-module rules, not physiology. The report says so, with the numbers that show why.
