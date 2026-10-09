-- OHDSI results-schema COHORT table: one row per person-episode in a cohort.
-- cohort_definition_id 1 = incident type 2 diabetes (see cohort_definition).
select
    1::integer           as cohort_definition_id,
    person_id::integer   as subject_id,
    index_date           as cohort_start_date,
    exit_date            as cohort_end_date
from {{ ref('t2dm_cohort_steps') }}
where in_observation and adult and observed_lookback and no_t1dm
