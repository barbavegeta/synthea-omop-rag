-- Every distinct (code system, code) that needs a concept: event codes, coded values and
-- units. Mapping happens once per distinct code (int_concept_map). Race, ethnicity,
-- gender and visit class use small explicit crosswalk seeds instead (see _seeds.yml).
with event_codings as (
    select c ->> 'system' as fhir_system, c ->> 'code' as code, c ->> 'display' as display
    from {{ ref('int_events') }} e
    cross join lateral jsonb_array_elements(e.codings) c
),

value_codings as (
    select c ->> 'system', c ->> 'code', c ->> 'display'
    from {{ ref('int_events') }} e
    cross join lateral jsonb_array_elements(e.value_codings) c
),

units as (
    select 'http://unitsofmeasure.org', unit_code, unit_text
    from {{ ref('int_events') }}
    where unit_code is not null
),

all_codes as (
    select * from event_codings
    union all select * from value_codings
    union all select * from units
)

select fhir_system, code, min(display) as display
from all_codes
where code is not null
group by fhir_system, code
