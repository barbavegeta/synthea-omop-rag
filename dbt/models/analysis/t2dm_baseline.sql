-- One row per cohort member: baseline features at index for the characterisation table.
--   conditions  any time on or before index ("history of"): chronic conditions are
--               recorded once at onset, so a 365-day window would miss most of them
--   drugs       any exposure in the 365 days before index (ATC level 2 classes)
--   BMI, HbA1c  the last value in the 365 days before index; HbA1c both with and without
--               values outside the Phase 2 plausibility limits (primary vs sensitivity)
{% set history_sets = ['hypertension', 'dyslipidaemia', 'ischaemic_heart_disease',
                       'chronic_kidney_disease', 'obesity', 'prediabetes', 'diabetic_complication'] %}
{% set drug_sets = ['metformin', 'atc_a10_diabetes_drugs', 'atc_c10_lipid_modifying',
                    'atc_c09_ras_agents', 'atc_c07_beta_blockers'] %}

with cohort as (
    select subject_id as person_id, cohort_start_date as index_date, cohort_end_date as exit_date
    from {{ ref('cohort') }}
    where cohort_definition_id = 1
),

members as (
    select * from {{ ref('concept_set_members') }}
),

ranges as (
    select * from {{ ref('measurement_plausible_ranges') }}
),

baseline_measures as (
    select
        c.person_id, ms.concept_set, m.measurement_date, m.value_as_number,
        (m.value_as_number between r.plausible_low and r.plausible_high) as plausible,
        row_number() over (partition by c.person_id, ms.concept_set
                           order by m.measurement_date desc, m.measurement_id desc) as recency,
        row_number() over (partition by c.person_id, ms.concept_set,
                                        (m.value_as_number between r.plausible_low and r.plausible_high)
                           order by m.measurement_date desc, m.measurement_id desc) as recency_by_plausibility
    from cohort c
    join {{ ref('measurement') }} m
      on m.person_id = c.person_id
     and m.measurement_date between c.index_date - 365 and c.index_date
    join members ms on ms.concept_id = m.measurement_concept_id and ms.concept_set in ('bmi', 'hba1c')
    left join ranges r
      on r.loinc_code = m.measurement_source_value and r.unit_code = m.unit_source_value
)

select
    c.person_id,
    c.index_date,
    c.exit_date,
    (c.exit_date - c.index_date)                                       as follow_up_days,
    extract(year from age(c.index_date, p.birth_datetime))::integer    as age_at_index,
    coalesce(gc.concept_name, 'Unknown')                               as sex,
    coalesce(rc.concept_name, 'Unknown')                               as race,
    coalesce(ec.concept_name, 'Unknown')                               as ethnicity,
{% for s in history_sets %}
    exists (
        select 1 from {{ ref('condition_occurrence') }} co
        join members m on m.concept_id = co.condition_concept_id and m.concept_set = '{{ s }}'
        where co.person_id = c.person_id and co.condition_start_date <= c.index_date
    )                                                                  as hx_{{ s }},
{% endfor %}
{% for s in drug_sets %}
    exists (
        select 1 from {{ ref('drug_exposure') }} de
        join members m on m.concept_id = de.drug_concept_id and m.concept_set = '{{ s }}'
        where de.person_id = c.person_id
          and de.drug_exposure_start_date between c.index_date - 365 and c.index_date - 1
    )                                                                  as rx_{{ s }},
{% endfor %}
    (select value_as_number from baseline_measures b
     where b.person_id = c.person_id and b.concept_set = 'bmi' and b.recency = 1)
                                                                       as baseline_bmi,
    (select value_as_number from baseline_measures b
     where b.person_id = c.person_id and b.concept_set = 'hba1c' and b.plausible
       and b.recency_by_plausibility = 1)                              as baseline_hba1c,
    (select value_as_number from baseline_measures b
     where b.person_id = c.person_id and b.concept_set = 'hba1c' and b.recency = 1)
                                                                       as baseline_hba1c_all_values
from cohort c
join {{ ref('person') }} p using (person_id)
left join {{ source('vocab', 'concept') }} gc on gc.concept_id = p.gender_concept_id and p.gender_concept_id <> 0
left join {{ source('vocab', 'concept') }} rc on rc.concept_id = p.race_concept_id and p.race_concept_id <> 0
left join {{ source('vocab', 'concept') }} ec on ec.concept_id = p.ethnicity_concept_id and p.ethnicity_concept_id <> 0
