-- Cohort attrition: persons remaining after each criterion, applied in order.
select 1 as step, 'Any type 2 diabetes record (first record = index date)' as criterion,
       count(*) as persons
from {{ ref('t2dm_cohort_steps') }}
union all
select 2, 'Index date inside observation period', count(*) filter (where in_observation)
from {{ ref('t2dm_cohort_steps') }}
union all
select 3, 'Aged 18 or over at index', count(*) filter (where in_observation and adult)
from {{ ref('t2dm_cohort_steps') }}
union all
select 4, 'At least one visit in the 365 days before index (observed look-back)',
       count(*) filter (where in_observation and adult and observed_lookback)
from {{ ref('t2dm_cohort_steps') }}
union all
select 5, 'No type 1 diabetes record on or before index',
       count(*) filter (where in_observation and adult and observed_lookback and no_t1dm)
from {{ ref('t2dm_cohort_steps') }}
