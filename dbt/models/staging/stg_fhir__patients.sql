-- One row per Patient. Race and ethnicity come from US Core extensions (OMB category).
with patients as (
    select resource_id as patient_id, payload
    from {{ source('raw', 'fhir_resource') }}
    where resource_type = 'Patient'
)

select
    p.patient_id,
    p.payload ->> 'gender'                                  as gender,
    (p.payload ->> 'birthDate')::date                       as birth_date,
    {{ fhir_ts("p.payload ->> 'deceasedDateTime'") }}       as deceased_datetime,
    race.system                                             as race_system,
    race.code                                               as race_code,
    race.display                                            as race_display,
    eth.system                                              as ethnicity_system,
    eth.code                                                as ethnicity_code,
    eth.display                                             as ethnicity_display
from patients p
left join lateral (
    select sub #>> '{valueCoding,system}' as system,
           sub #>> '{valueCoding,code}'   as code,
           sub #>> '{valueCoding,display}' as display
    from jsonb_array_elements(p.payload -> 'extension') e
    cross join lateral jsonb_array_elements(e -> 'extension') sub
    where e ->> 'url' = 'http://hl7.org/fhir/us/core/StructureDefinition/us-core-race'
      and sub ->> 'url' = 'ombCategory'
    limit 1
) race on true
left join lateral (
    select sub #>> '{valueCoding,system}' as system,
           sub #>> '{valueCoding,code}'   as code,
           sub #>> '{valueCoding,display}' as display
    from jsonb_array_elements(p.payload -> 'extension') e
    cross join lateral jsonb_array_elements(e -> 'extension') sub
    where e ->> 'url' = 'http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity'
      and sub ->> 'url' = 'ombCategory'
    limit 1
) eth on true
