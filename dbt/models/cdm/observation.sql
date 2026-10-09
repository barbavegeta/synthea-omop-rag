select
    row_number() over (order by event_id, concept_id)::integer  as observation_id,
    person_id::integer                                      as person_id,
    concept_id::integer                                     as observation_concept_id,
    start_datetime::date                                    as observation_date,
    start_datetime                                          as observation_datetime,
    {{ var('type_ehr') }}::integer                          as observation_type_concept_id,
    value_number::double precision                          as value_as_number,
    value_as_string                                         as value_as_string,
    value_as_concept_id::integer                            as value_as_concept_id,
    null::integer                                           as qualifier_concept_id,
    unit_concept_id::integer                                as unit_concept_id,
    null::integer                                           as provider_id,
    visit_occurrence_id::integer                            as visit_occurrence_id,
    null::integer                                           as visit_detail_id,
    source_code                                             as observation_source_value,
    source_concept_id::integer                              as observation_source_concept_id,
    unit_code                                               as unit_source_value,
    null::text                                              as qualifier_source_value,
    value_source_value                                      as value_source_value,
    null::integer                                           as observation_event_id,
    null::integer                                           as obs_event_field_concept_id
from {{ ref('int_events_mapped') }}
where domain_id = 'Observation'
