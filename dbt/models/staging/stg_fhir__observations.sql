-- One row per Observation *value*: a panel (e.g. blood pressure) with `component`s
-- becomes one row per component, each with its own code and value. component_index is
-- 0 for a plain observation, 1..n for components.
with obs as (
    select resource_id, patient_id, payload
    from {{ source('raw', 'fhir_resource') }}
    where resource_type = 'Observation'
),

values_ as (
    select resource_id, patient_id, payload, 0 as component_index, payload as v
    from obs
    where not payload ? 'component'
    union all
    select o.resource_id, o.patient_id, o.payload, c.idx::int as component_index, c.v
    from obs o
    cross join lateral jsonb_array_elements(o.payload -> 'component') with ordinality as c(v, idx)
)

select
    resource_id || '#' || component_index                   as observation_value_id,
    resource_id                                             as observation_id,
    component_index,
    patient_id,
    {{ fhir_ref("payload #>> '{encounter,reference}'") }}   as encounter_id,
    payload #>> '{category,0,coding,0,code}'                as category,
    {{ fhir_codings("v -> 'code'") }}                       as codings,
    v #>> '{code,text}'                                     as code_text,
    {{ fhir_ts("payload ->> 'effectiveDateTime'") }}        as effective_datetime,
    (v #>> '{valueQuantity,value}')::numeric                as value_number,
    v #>> '{valueQuantity,code}'                            as unit_code,
    v #>> '{valueQuantity,unit}'                            as unit_text,
    {{ fhir_codings("v -> 'valueCodeableConcept'") }}       as value_codings,
    v #>> '{valueCodeableConcept,text}'                     as value_text,
    v ->> 'valueString'                                     as value_string
from values_
