with patients as (
    select p.*, pid.person_id
    from {{ ref('stg_fhir__patients') }} p
    join {{ ref('int_person_ids') }} pid using (patient_id)
),

crosswalk as (
    select m.source_code, c.concept_id, c.vocabulary_id
    from {{ ref('race_ethnicity_map') }} m
    join {{ source('vocab', 'concept') }} c
      on c.vocabulary_id = m.vocabulary_id and c.concept_code = m.concept_code
),

gender as (
    select g.source_value, c.concept_id
    from {{ ref('gender_map') }} g
    join {{ source('vocab', 'concept') }} c
      on c.vocabulary_id = g.vocabulary_id and c.concept_code = g.concept_code
)

select
    p.person_id::integer                                    as person_id,
    coalesce(g.concept_id, 0)::integer                      as gender_concept_id,
    extract(year from p.birth_date)::integer                as year_of_birth,
    extract(month from p.birth_date)::integer               as month_of_birth,
    extract(day from p.birth_date)::integer                 as day_of_birth,
    p.birth_date::timestamp                                 as birth_datetime,
    coalesce(r.concept_id, 0)::integer                      as race_concept_id,
    coalesce(e.concept_id, 0)::integer                      as ethnicity_concept_id,
    null::integer                                           as location_id,
    null::integer                                           as provider_id,
    null::integer                                           as care_site_id,
    p.patient_id                                            as person_source_value,
    p.gender                                                as gender_source_value,
    0::integer                                              as gender_source_concept_id,
    p.race_code                                             as race_source_value,
    0::integer                                              as race_source_concept_id,
    p.ethnicity_code                                        as ethnicity_source_value,
    0::integer                                              as ethnicity_source_concept_id
from patients p
left join gender g on g.source_value = p.gender
left join crosswalk r on r.source_code = p.race_code and r.vocabulary_id = 'Race'
left join crosswalk e on e.source_code = p.ethnicity_code and e.vocabulary_id = 'Ethnicity'
