# ADR-0007: drug_exposure sources, de-duplication and end dates

**Status:** accepted (Phase 2; end-date rule chosen by the project owner)

## Context
`drug_exposure_end_date` is **required** in CDM v5.4. Synthea's `MedicationRequest`s carry no quantity, days supply, validity period or stop date: only `authoredOn` and a snapshot `status`. Chronic drugs are re-prescribed at regular intervals: median 21 days for insulin, lisinopril and metformin, 28 for hydrochlorothiazide and amlodipine, 365 for simvastatin.

## Decisions
1. **Sources:** outpatient prescriptions (`MedicationRequest` with an inline RxNorm code, 38,284), inpatient administrations (`MedicationAdministration`, 17,397) and immunizations (`Immunization`, CVX, 16,597).
2. **De-duplication:** the 17,397 `MedicationRequest`s that use `medicationReference` are **excluded**. Each one matches exactly one `MedicationAdministration` on patient, encounter, drug and **identical timestamp** (verified: 17,397 of 17,397). Synthea records each inpatient drug as both an order and a dose. Keeping both would double-count, and the administration is the more specific record.
3. **End dates:** the OHDSI THEMIS ratified convention, *"How to determine drug_exposure_end_date when it is not given explicitly in the data"*:
   - written prescription → `start + 29` (a 30-day exposure);
   - administration record → `end = start`.

   Immunizations are administrations.
4. `days_supply`, `quantity` and `verbatim_end_date` stay **NULL**. The CDM field spec says days_supply "should not be calculated from other fields".
5. Type concepts: 32838 *EHR prescription*; 32818 *EHR administration record*. A dbt test checks both ids against the vocabulary.

## Alternative considered
**Gap-fill**: each prescription lasts until the same drug is next prescribed, with a cap. It fits Synthea's cadence better, especially yearly statins. Rejected: it is not an OHDSI convention, and it uses later records to set earlier ones.

## Known distortion (documented, not fixed)
Drugs Synthea re-prescribes only yearly (simvastatin) appear as 30 days of exposure per year. Any "current medication" ground truth in Phase 4 uses **this same rule**, so the evaluation is internally consistent, but the rule's limitation applies to it too.
