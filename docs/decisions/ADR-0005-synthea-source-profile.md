# ADR-0005: Synthea configuration, and what the FHIR source actually contains

**Status:** accepted. Findings come from profiling the 22-bundle CI population (Synthea 4.0.0); counts are from that sample.

## Configuration
- FHIR R4 patient bundles only (US Core 6.1.0 profiles, transaction bundles). All other exporters are off.
- **Hospital and practitioner bundles are off.** They would feed `care_site` and `provider`, which are outside this CDM subset. Consequence: patient bundles keep *conditional references* such as `Practitioner?identifier=...|9999982090` that resolve to nothing in our data. Synthea warns about this at run time, and the warning is expected.
- **Synthea's own clinical notes** (`DocumentReference`, one per encounter, base64 text) are still embedded in the bundles and land in the raw layer. They are **not** used for RAG, because they don't carry the labelled negation, history and family-history phenomena the evaluation needs (see the Phase 4 notes ADR).
- `-p 1000` counts **living** patients; Synthea adds the deceased (CI: `-p 20` gave 22 bundles, 2 deceased).

## Source facts that shape the OMOP ETL
| Finding | Consequence |
|---|---|
| `MedicationRequest` has **no end date and no supply duration**: no `dispenseRequest`, no `validityPeriod`; only `status` (`completed` / `active`) and `authoredOn`. Claims carry only the encounter's billing period. | `drug_exposure_end_date` must be imputed by a documented rule (decided in Phase 2). The ground truth in Phase 4 uses the same rule. |
| `Condition.code` is mostly SNOMED, but **about 4% is ICD-10** (27 of 755). | Athena download must include **ICD10CM**. |
| `Procedure.code` includes **CDT** (ADA dental codes, 219 of 2,715). | CDT is ADA-licensed, so these are expected to stay unmapped (`concept_id = 0`). The coverage metric will show this rather than hide it. |
| `Observation` categories: laboratory, vital-signs, survey, social-history, plus a few procedure, exam, imaging and therapy. Values: `valueQuantity`, `valueCodeableConcept`, `valueString`, and **`component`** (e.g. blood pressure panels). | Panels must be unnested so each component becomes its own measurement. Survey and social-history items will mostly route to the OBSERVATION domain. |
| Many SNOMED "conditions" are social findings ("Received higher education (finding)", employment, stress). | Routing by **standard concept domain** sends them to OBSERVATION, which is why that table was added. |
| `exporter.years_of_history = 10` is **not a hard cut-off**: CI encounters span 1982–2025, with most from 2016 on. Older records survive when they carry long-lived state (e.g. an active condition onset in 1993). | Observation periods will sometimes start decades before the bulk of the data. This is documented, not "fixed". |
| All `subject` references use `urn:uuid:` (transaction-bundle style); each bundle holds exactly one Patient. | The loader tags every resource with its bundle's Patient id instead of parsing references. |
| Also present, but outside the CDM subset: Claim and ExplanationOfBenefit (cost), DiagnosticReport, CarePlan, CareTeam, Device, SupplyDelivery, AllergyIntolerance, ImagingStudy, Provenance. | Kept in the raw layer (lossless). Not mapped; listed as a limitation. |
