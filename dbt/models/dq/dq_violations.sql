{#
  Every data-quality violation in the CDM, one row each (ADR-0009). Each check is a
  query, and the checks live in a *model* rather than directly in tests, so that
    1. dbt unit tests can feed in deliberately bad rows and prove each check fires;
    2. the violations are a queryable table, not just a pass/fail line in a log.
  Tests on this model (_dq.yml) then assert "no rows for check X" at a chosen severity.
#}
{% set event_tables = [
    {'table': 'condition_occurrence', 'id': 'condition_occurrence_id', 'start': 'condition_start_date', 'end': 'condition_end_date'},
    {'table': 'drug_exposure',        'id': 'drug_exposure_id',        'start': 'drug_exposure_start_date', 'end': 'drug_exposure_end_date'},
    {'table': 'procedure_occurrence', 'id': 'procedure_occurrence_id', 'start': 'procedure_date', 'end': 'procedure_end_date'},
    {'table': 'measurement',          'id': 'measurement_id',          'start': 'measurement_date', 'end': none},
    {'table': 'observation',          'id': 'observation_id',          'start': 'observation_date', 'end': none},
    {'table': 'visit_occurrence',     'id': 'visit_occurrence_id',     'start': 'visit_start_date', 'end': 'visit_end_date'},
] %}

with death as (
    select person_id, death_date from {{ ref('death') }}
),

birth as (
    select person_id, birth_datetime::date as birth_date from {{ ref('person') }}
),

op as (
    select person_id, observation_period_start_date as op_start, observation_period_end_date as op_end
    from {{ ref('observation_period') }}
),

ranges as (
    select * from {{ ref('measurement_plausible_ranges') }}
)

{% for t in event_tables %}
-- {{ t.table }}: starts more than death_grace_days after death. Same rule as OHDSI DQD
-- plausibleBeforeDeath (60 days): death certification legitimately happens after death.
-- Only the start is checked: imputed drug end dates may run past death.
select 'event_after_death' as check_name, '{{ t.table }}' as cdm_table, e.{{ t.id }} as record_id,
       e.person_id, e.{{ t.start }} as event_date, 'death ' || d.death_date as detail
from {{ ref(t.table) }} e join death d using (person_id)
where e.{{ t.start }} > d.death_date + {{ var('death_grace_days') }}
union all
-- {{ t.table }}: starts before birth
select 'event_before_birth', '{{ t.table }}', e.{{ t.id }}, e.person_id, e.{{ t.start }},
       'birth ' || b.birth_date
from {{ ref(t.table) }} e join birth b using (person_id)
where e.{{ t.start }} < b.birth_date
union all
-- {{ t.table }}: starts outside the person's observation period (or person has none)
select 'event_outside_observation_period', '{{ t.table }}', e.{{ t.id }}, e.person_id, e.{{ t.start }},
       coalesce('period ' || op.op_start || ' to ' || op.op_end, 'no observation period')
from {{ ref(t.table) }} e left join op using (person_id)
where op.person_id is null or e.{{ t.start }} not between op.op_start and op.op_end
union all
{% if t.end %}
-- {{ t.table }}: ends before it starts
select 'end_before_start', '{{ t.table }}', e.{{ t.id }}, e.person_id, e.{{ t.start }},
       'end ' || e.{{ t.end }}
from {{ ref(t.table) }} e
where e.{{ t.end }} < e.{{ t.start }}
union all
{% endif %}
{% endfor %}

-- measurement values outside physiological plausibility limits (seed, per LOINC + unit)
select 'implausible_measurement_value', 'measurement', m.measurement_id, m.person_id,
       m.measurement_date,
       r.label || ' = ' || m.value_as_number || ' ' || m.unit_source_value
           || ' (plausible ' || r.plausible_low || '-' || r.plausible_high || ')'
from {{ ref('measurement') }} m
join ranges r on r.loinc_code = m.measurement_source_value and r.unit_code = m.unit_source_value
where m.value_as_number not between r.plausible_low and r.plausible_high

union all

select 'death_before_birth', 'death', d.person_id, d.person_id, d.death_date, 'birth ' || b.birth_date
from death d join birth b using (person_id)
where d.death_date < b.birth_date

union all

select 'observation_period_end_before_start', 'observation_period', op.person_id, op.person_id,
       op.op_start, 'end ' || op.op_end
from op
where op.op_end < op.op_start
