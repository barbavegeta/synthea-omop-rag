select
    row_number() over (order by event_id, concept_id)::integer  as condition_occurrence_id,
    person_id::integer                                      as person_id,
    concept_id::integer                                     as condition_concept_id,
    start_datetime::date                                    as condition_start_date,
    start_datetime                                          as condition_start_datetime,
    end_datetime::date                                      as condition_end_date,
    end_datetime                                            as condition_end_datetime,
    {{ var('type_ehr') }}::integer                          as condition_type_concept_id,
    null::integer                                           as condition_status_concept_id,
    null::text                                              as stop_reason,
    null::integer                                           as provider_id,
    visit_occurrence_id::integer                            as visit_occurrence_id,
    null::integer                                           as visit_detail_id,
    source_code                                             as condition_source_value,
    source_concept_id::integer                              as condition_source_concept_id,
    null::text                                              as condition_status_source_value
from {{ ref('int_events_mapped') }}
where domain_id = 'Condition'
