select
    row_number() over (order by event_id, concept_id)::integer  as procedure_occurrence_id,
    person_id::integer                                      as person_id,
    concept_id::integer                                     as procedure_concept_id,
    start_datetime::date                                    as procedure_date,
    start_datetime                                          as procedure_datetime,
    end_datetime::date                                      as procedure_end_date,
    end_datetime                                            as procedure_end_datetime,
    {{ var('type_ehr') }}::integer                          as procedure_type_concept_id,
    null::integer                                           as modifier_concept_id,
    null::integer                                           as quantity,
    null::integer                                           as provider_id,
    visit_occurrence_id::integer                            as visit_occurrence_id,
    null::integer                                           as visit_detail_id,
    source_code                                             as procedure_source_value,
    source_concept_id::integer                              as procedure_source_concept_id,
    null::text                                              as modifier_source_value
from {{ ref('int_events_mapped') }}
where domain_id = 'Procedure'
