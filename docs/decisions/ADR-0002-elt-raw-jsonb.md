# ADR-0002: Land FHIR as raw JSONB; parse in dbt (ELT)

**Status:** accepted

## Context
Synthea writes one FHIR R4 *Bundle* per patient: a JSON document holding many *resources* (Patient, Encounter, Condition, MedicationRequest, Observation, Procedure and so on) that reference each other by id. These have to become OMOP CDM tables.

## Options
1. **ETL:** Python extracts the needed fields into typed tables per resource type, and dbt maps from there.
2. **ELT:** Python only splits bundles into one row per resource, `raw.fhir_resource(resource_type, resource_id, patient_ref, bundle_file, payload jsonb)`, and bulk-loads them with COPY. dbt staging models extract typed fields with Postgres JSONB operators.

## Decision
Option 2.
- **The raw layer is lossless.** If a later phase needs a field nobody extracted (for example `MedicationRequest.dosageInstruction`), it is already in the database, and no re-ingestion is needed.
- **All field logic sits in one place**: versioned SQL in dbt, with lineage, documentation and tests. Python ETL would split that logic between pytest-tested Python and dbt.
- **Python's job stays small and testable**: correct splitting, reference extraction and fast bulk load.

## Consequences
- The raw table is larger than typed extracts would be, which is fine at this scale.
- JSONB path expressions in SQL are more verbose than Python attribute access. Staging models keep them in exactly one layer.
- Interview framing: this is the standard modern warehouse pattern (land raw, transform in-warehouse). The trade-off is storage and SQL verbosity in return for replayability and a single place for transformation logic.
