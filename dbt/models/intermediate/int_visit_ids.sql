select
    encounter_id,
    row_number() over (order by encounter_id)::integer as visit_occurrence_id
from {{ ref('stg_fhir__encounters') }}
