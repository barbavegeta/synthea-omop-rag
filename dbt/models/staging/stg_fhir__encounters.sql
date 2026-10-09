-- One row per Encounter (becomes visit_occurrence).
select
    resource_id                                             as encounter_id,
    patient_id,
    payload #>> '{class,code}'                              as class_code,
    {{ fhir_codings("payload -> 'type' -> 0") }}            as type_codings,
    payload #>> '{type,0,text}'                             as type_text,
    {{ fhir_ts("payload #>> '{period,start}'") }}           as start_datetime,
    {{ fhir_ts("payload #>> '{period,end}'") }}             as end_datetime,
    payload #>> '{reasonCode,0,coding,0,code}'              as reason_code,
    payload #>> '{reasonCode,0,text}'                       as reason_text
from {{ source('raw', 'fhir_resource') }}
where resource_type = 'Encounter'
