-- Death date from Patient.deceasedDateTime. Cause from the death-certificate
-- Observation (LOINC 69453-9) whose value is a SNOMED code: present for 147 of 151
-- deceased patients; the other 4 get cause_concept_id NULL (unknown, not "no cause").
with cause as (
    select distinct on (person_id)
        person_id, value_as_concept_id, value_source_value
    from {{ ref('int_events_mapped') }}
    where source_table = 'observation' and source_code = '69453-9'
    order by person_id, start_datetime desc
)

select
    pid.person_id::integer                                  as person_id,
    p.deceased_datetime::date                               as death_date,
    p.deceased_datetime                                     as death_datetime,
    {{ var('type_ehr') }}::integer                          as death_type_concept_id,
    c.value_as_concept_id::integer                          as cause_concept_id,
    c.value_source_value                                    as cause_source_value,
    null::integer                                           as cause_source_concept_id
from {{ ref('stg_fhir__patients') }} p
join {{ ref('int_person_ids') }} pid using (patient_id)
left join cause c on c.person_id = pid.person_id
where p.deceased_datetime is not null
