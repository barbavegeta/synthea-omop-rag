-- One period per person, spanning first to last visit (ADR-0008). Visits stand in for
-- enrolment, which EHR data does not record. Because the period is derived from visits
-- only, "every other event falls inside it" is a real check, not true by construction.
select
    row_number() over (order by person_id)::integer         as observation_period_id,
    person_id::integer                                      as person_id,
    min(visit_start_date)                                   as observation_period_start_date,
    max(visit_end_date)                                     as observation_period_end_date,
    {{ var('type_ehr') }}::integer                          as period_type_concept_id
from {{ ref('visit_occurrence') }}
group by person_id
