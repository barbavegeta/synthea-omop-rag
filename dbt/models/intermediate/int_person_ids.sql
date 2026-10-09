-- OMOP keys are integers; FHIR ids are UUIDs. Dense, deterministic integers: the same
-- input always yields the same ids. person_source_value keeps the FHIR id for traceability.
select
    patient_id,
    row_number() over (order by patient_id)::integer as person_id
from {{ ref('stg_fhir__patients') }}
