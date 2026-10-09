-- Every HbA1c value of every cohort member, positioned relative to the index date and
-- flagged against the Phase 2 plausibility limits (primary analysis excludes implausible).
select
    c.subject_id                                        as person_id,
    m.measurement_date,
    m.measurement_date - c.cohort_start_date            as days_from_index,
    m.value_as_number                                   as hba1c_pct,
    coalesce(m.value_as_number between r.plausible_low and r.plausible_high, false) as plausible,
    case
        when m.measurement_date - c.cohort_start_date between -365 and 0    then '1 baseline (-365 to 0 d)'
        when m.measurement_date - c.cohort_start_date between 1 and 182     then '2 0-6 months'
        when m.measurement_date - c.cohort_start_date between 183 and 365   then '3 6-12 months'
        when m.measurement_date - c.cohort_start_date between 366 and 730   then '4 1-2 years'
        when m.measurement_date - c.cohort_start_date between 731 and 1825  then '5 2-5 years'
        when m.measurement_date - c.cohort_start_date > 1825                then '6 >5 years'
    end                                                 as window_label
from {{ ref('cohort') }} c
join {{ ref('measurement') }} m on m.person_id = c.subject_id
join {{ ref('concept_set_members') }} cs on cs.concept_id = m.measurement_concept_id and cs.concept_set = 'hba1c'
left join {{ ref('measurement_plausible_ranges') }} r
  on r.loinc_code = m.measurement_source_value and r.unit_code = m.unit_source_value
where c.cohort_definition_id = 1
  and m.measurement_date between c.cohort_start_date - 365 and c.cohort_end_date
