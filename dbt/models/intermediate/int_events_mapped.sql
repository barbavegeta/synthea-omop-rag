-- Each event, mapped and routed. Rules (ADR-0006):
--  * Coding choice: an element can carry several codings (5,300 observations do). Use the
--    first coding that maps to a standard concept; if none does, the first coding.
--  * One-to-many maps: one output row per standard target (OMOP convention).
--  * Domain: the standard concept's domain decides the CDM table. Unmapped events
--    (concept_id 0) fall back to the domain their FHIR resource implies, so they still
--    land in the CDM, visibly unmapped, rather than vanishing.
with events as (
    select * from {{ ref('int_events') }}
),

map as (
    select * from {{ ref('int_concept_map') }}
),

codings as (
    select e.event_id, c.idx::integer as coding_index,
           c.v ->> 'system' as fhir_system, c.v ->> 'code' as code
    from events e
    cross join lateral jsonb_array_elements(e.codings) with ordinality as c(v, idx)
),

chosen_coding as (
    select distinct on (co.event_id)
        co.event_id, co.fhir_system, co.code
    from codings co
    join map m on m.fhir_system = co.fhir_system and m.code = co.code and m.target_rank = 1
    order by co.event_id, (m.target_concept_id <> 0) desc, co.coding_index
),

value_concept as (
    select e.event_id, m.target_concept_id as value_as_concept_id, m.code as value_source_code
    from events e
    cross join lateral (
        select c ->> 'system' as fhir_system, c ->> 'code' as code
        from jsonb_array_elements(e.value_codings) with ordinality as x(c, idx)
        order by idx limit 1
    ) v
    join map m on m.fhir_system = v.fhir_system and m.code = v.code and m.target_rank = 1
)

select
    e.event_id,
    e.source_table,
    e.record_kind,
    e.category,
    pid.person_id,
    vid.visit_occurrence_id,
    ch.code                                                   as source_code,
    ch.fhir_system,
    coalesce(m.source_concept_id, 0)                          as source_concept_id,
    coalesce(m.target_concept_id, 0)                          as concept_id,
    coalesce(m.mapping_status, 'no_coding')                   as mapping_status,
    case
        when m.target_concept_id <> 0 then m.target_domain_id
        when e.source_table = 'condition' then 'Condition'
        when e.source_table = 'procedure' then 'Procedure'
        when e.source_table = 'drug' then 'Drug'
        when e.category in ('laboratory', 'vital-signs') then 'Measurement'
        else 'Observation'
    end                                                       as domain_id,
    e.start_datetime,
    e.end_datetime,
    e.value_number,
    e.unit_code,
    coalesce(u.target_concept_id, case when e.unit_code is not null then 0 end)
                                                              as unit_concept_id,
    vc.value_as_concept_id,
    coalesce(vc.value_source_code, e.value_string)            as value_source_value,
    coalesce(e.value_string, e.value_text)                    as value_as_string,
    e.code_text
from events e
join {{ ref('int_person_ids') }} pid on pid.patient_id = e.patient_id
left join {{ ref('int_visit_ids') }} vid on vid.encounter_id = e.encounter_id
left join chosen_coding ch on ch.event_id = e.event_id
left join map m on m.fhir_system = ch.fhir_system and m.code = ch.code
left join map u
       on u.fhir_system = 'http://unitsofmeasure.org' and u.code = e.unit_code and u.target_rank = 1
left join value_concept vc on vc.event_id = e.event_id
