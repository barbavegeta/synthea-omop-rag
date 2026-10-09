with visit_concepts as (
    select m.class_code, c.concept_id
    from {{ ref('visit_class_map') }} m
    join {{ source('vocab', 'concept') }} c
      on c.vocabulary_id = m.vocabulary_id and c.concept_code = m.concept_code
)

select
    vid.visit_occurrence_id::integer                        as visit_occurrence_id,
    pid.person_id::integer                                  as person_id,
    coalesce(vc.concept_id, 0)::integer                     as visit_concept_id,
    e.start_datetime::date                                  as visit_start_date,
    e.start_datetime                                        as visit_start_datetime,
    coalesce(e.end_datetime, e.start_datetime)::date        as visit_end_date,
    coalesce(e.end_datetime, e.start_datetime)              as visit_end_datetime,
    {{ var('type_ehr') }}::integer                          as visit_type_concept_id,
    null::integer                                           as provider_id,
    null::integer                                           as care_site_id,
    e.class_code                                            as visit_source_value,
    0::integer                                              as visit_source_concept_id,
    null::integer                                           as admitted_from_concept_id,
    null::text                                              as admitted_from_source_value,
    null::integer                                           as discharged_to_concept_id,
    null::text                                              as discharged_to_source_value,
    lag(vid.visit_occurrence_id) over (
        partition by pid.person_id order by e.start_datetime, vid.visit_occurrence_id
    )::integer                                              as preceding_visit_occurrence_id
from {{ ref('stg_fhir__encounters') }} e
join {{ ref('int_visit_ids') }} vid using (encounter_id)
join {{ ref('int_person_ids') }} pid using (patient_id)
left join visit_concepts vc on vc.class_code = e.class_code
