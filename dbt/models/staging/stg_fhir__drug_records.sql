-- Every drug-like record, one row each, with the kind of record it is. The kind drives
-- the drug_exposure end-date rule and type concept (ADR-0007):
--   prescription    MedicationRequest with an inline RxNorm code (outpatient)
--   administration  MedicationAdministration (inpatient dose given)
--   immunization    Immunization (CVX)
-- MedicationRequests that use medicationReference are excluded: each one duplicates a
-- MedicationAdministration (same patient, encounter, drug and timestamp; verified on the
-- full population, 17,397 of 17,397), so keeping both would double-count inpatient drugs.
select
    resource_id                                             as drug_record_id,
    'prescription'                                          as record_kind,
    patient_id,
    {{ fhir_ref("payload #>> '{encounter,reference}'") }}   as encounter_id,
    {{ fhir_codings("payload -> 'medicationCodeableConcept'") }} as codings,
    payload #>> '{medicationCodeableConcept,text}'          as code_text,
    {{ fhir_ts("payload ->> 'authoredOn'") }}               as start_datetime,
    payload ->> 'status'                                    as status
from {{ source('raw', 'fhir_resource') }}
where resource_type = 'MedicationRequest'
  and payload ? 'medicationCodeableConcept'

union all

select
    resource_id,
    'administration',
    patient_id,
    {{ fhir_ref("payload #>> '{context,reference}'") }},
    {{ fhir_codings("payload -> 'medicationCodeableConcept'") }},
    payload #>> '{medicationCodeableConcept,text}',
    {{ fhir_ts("payload ->> 'effectiveDateTime'") }},
    payload ->> 'status'
from {{ source('raw', 'fhir_resource') }}
where resource_type = 'MedicationAdministration'

union all

select
    resource_id,
    'immunization',
    patient_id,
    {{ fhir_ref("payload #>> '{encounter,reference}'") }},
    {{ fhir_codings("payload -> 'vaccineCode'") }},
    payload #>> '{vaccineCode,text}',
    {{ fhir_ts("payload ->> 'occurrenceDateTime'") }},
    payload ->> 'status'
from {{ source('raw', 'fhir_resource') }}
where resource_type = 'Immunization'
