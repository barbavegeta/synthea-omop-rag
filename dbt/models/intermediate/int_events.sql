-- Every coded clinical event in one shape, whatever FHIR resource it came from. The CDM
-- table an event lands in is decided later by its *standard concept's domain*, not by
-- the resource type (int_events_mapped), so all events go through one mapping path.
select
    'condition'             as source_table,
    condition_id            as event_id,
    patient_id, encounter_id, codings, code_text,
    onset_datetime          as start_datetime,
    abatement_datetime      as end_datetime,
    null::text              as record_kind,
    null::text              as category,
    null::numeric           as value_number,
    null::text              as unit_code,
    null::text              as unit_text,
    '[]'::jsonb             as value_codings,
    null::text              as value_text,
    null::text              as value_string
from {{ ref('stg_fhir__conditions') }}

union all

select
    'procedure', procedure_id, patient_id, encounter_id, codings, code_text,
    start_datetime, end_datetime, null, null, null, null, null, '[]'::jsonb, null, null
from {{ ref('stg_fhir__procedures') }}

union all

select
    'observation', observation_value_id, patient_id, encounter_id, codings, code_text,
    effective_datetime, null, null, category, value_number, unit_code, unit_text,
    value_codings, value_text, value_string
from {{ ref('stg_fhir__observations') }}

union all

select
    'drug', drug_record_id, patient_id, encounter_id, codings, code_text,
    start_datetime, null, record_kind, null, null, null, null, '[]'::jsonb, null, null
from {{ ref('stg_fhir__drug_records') }}
