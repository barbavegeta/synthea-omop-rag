-- Metformin eras for cohort members, built with the OHDSI DRUG_ERA rule: exposures to the
-- same ingredient separated by a gap of <= 30 days are one continuous era. Each exposure
-- lasts start..end as set in drug_exposure (prescription = 30 days, ADR-0007), so the
-- era lengths inherit that assumption.
with exposures as (
    select de.person_id, de.drug_exposure_start_date as start_date, de.drug_exposure_end_date as end_date
    from {{ ref('drug_exposure') }} de
    join {{ ref('concept_set_members') }} m on m.concept_id = de.drug_concept_id and m.concept_set = 'metformin'
    join {{ ref('cohort') }} c on c.subject_id = de.person_id and c.cohort_definition_id = 1
),

flagged as (
    -- a new era starts at a person's first exposure, or when an exposure begins more than
    -- 30 days after every earlier one ended
    select *,
        case when coalesce(start_date > max(end_date) over (
                 partition by person_id order by start_date, end_date
                 rows between unbounded preceding and 1 preceding) + 30, true)
             then 1 else 0 end as new_era
    from exposures
),

numbered as (
    select *, sum(new_era) over (partition by person_id order by start_date, end_date) as era_number
    from flagged
)

select
    person_id,
    era_number::integer           as era_number,
    min(start_date)               as era_start_date,
    max(end_date)                 as era_end_date,
    count(*)::integer             as exposure_count
from numbered
group by person_id, era_number
