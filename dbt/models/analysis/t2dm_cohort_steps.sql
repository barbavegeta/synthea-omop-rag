-- Incident type 2 diabetes cohort (ADR-0010), one row per candidate person, with a flag
-- per criterion so the attrition table can be computed from the same logic.
--   entry      first-ever T2DM condition record (concept set t2dm, with descendants)
--   index      that record's start date
--   criteria   index inside the person's observation period
--              aged >= 18 at index
--              >= 1 visit in the 365 days before index: an *observed* look-back, so the
--                diagnosis is plausibly new and baseline data could have been captured
--              no type 1 diabetes record on or before index
--   exit       end of observation period, or death if earlier
with members as (
    select * from {{ ref('concept_set_members') }}
),

first_t2dm as (
    select co.person_id, min(co.condition_start_date) as index_date
    from {{ ref('condition_occurrence') }} co
    join members m on m.concept_id = co.condition_concept_id and m.concept_set = 't2dm'
    group by co.person_id
)

select
    f.person_id,
    f.index_date,
    least(op.observation_period_end_date, d.death_date)              as exit_date,
    extract(year from age(f.index_date, p.birth_datetime))::integer  as age_at_index,
    (f.index_date between op.observation_period_start_date
                      and op.observation_period_end_date)            as in_observation,
    (extract(year from age(f.index_date, p.birth_datetime)) >= 18)   as adult,
    exists (
        select 1 from {{ ref('visit_occurrence') }} v
        where v.person_id = f.person_id
          and v.visit_start_date between f.index_date - 365 and f.index_date - 1
    )                                                                as observed_lookback,
    not exists (
        select 1 from {{ ref('condition_occurrence') }} co
        join members m on m.concept_id = co.condition_concept_id and m.concept_set = 't1dm'
        where co.person_id = f.person_id and co.condition_start_date <= f.index_date
    )                                                                as no_t1dm
from first_t2dm f
join {{ ref('person') }} p using (person_id)
join {{ ref('observation_period') }} op using (person_id)
left join {{ ref('death') }} d using (person_id)
