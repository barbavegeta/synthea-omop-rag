-- One row per Procedure.
select
    resource_id                                             as procedure_id,
    patient_id,
    {{ fhir_ref("payload #>> '{encounter,reference}'") }}   as encounter_id,
    {{ fhir_codings("payload -> 'code'") }}                 as codings,
    payload #>> '{code,text}'                               as code_text,
    {{ fhir_ts("payload #>> '{performedPeriod,start}'") }}  as start_datetime,
    {{ fhir_ts("payload #>> '{performedPeriod,end}'") }}    as end_datetime
from {{ source('raw', 'fhir_resource') }}
where resource_type = 'Procedure'
