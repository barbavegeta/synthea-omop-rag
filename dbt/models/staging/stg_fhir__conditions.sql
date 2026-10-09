-- One row per Condition. Many are social "findings" that will route to OBSERVATION.
select
    resource_id                                             as condition_id,
    patient_id,
    {{ fhir_ref("payload #>> '{encounter,reference}'") }}   as encounter_id,
    {{ fhir_codings("payload -> 'code'") }}                 as codings,
    payload #>> '{code,text}'                               as code_text,
    payload #>> '{clinicalStatus,coding,0,code}'            as clinical_status,
    {{ fhir_ts("payload ->> 'onsetDateTime'") }}            as onset_datetime,
    {{ fhir_ts("payload ->> 'abatementDateTime'") }}        as abatement_datetime
from {{ source('raw', 'fhir_resource') }}
where resource_type = 'Condition'
