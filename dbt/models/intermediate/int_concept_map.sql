-- The concept-mapping engine. For each distinct source code:
--   1. FHIR system URL -> OHDSI vocabulary_id                    (seed fhir_code_systems)
--   2. (vocabulary_id, code) -> source concept                    (vocab.concept)
--   3. source concept --'Maps to'--> standard concept(s)          (vocab.concept_relationship)
-- A code can map to several standard concepts ("one-to-many"); OMOP convention is one
-- CDM record per target, so this model has one row per (code, target).
-- mapping_status explains every concept_id = 0, which feeds the coverage metric.
with codes as (
    select c.fhir_system, c.code, c.display, s.vocabulary_id
    from {{ ref('int_source_codes') }} c
    left join {{ ref('fhir_code_systems') }} s on s.fhir_system = c.fhir_system
),

with_source as (
    select codes.*, sc.concept_id as source_concept_id
    from codes
    left join {{ source('vocab', 'concept') }} sc
           on sc.vocabulary_id = codes.vocabulary_id
          and sc.concept_code = codes.code
),

with_targets as (
    select
        ws.*,
        t.concept_id as target_concept_id,
        t.domain_id  as target_domain_id,
        t.n_targets
    from with_source ws
    left join lateral (
        select tc.concept_id, tc.domain_id, count(*) over () as n_targets
        from {{ source('vocab', 'concept_relationship') }} cr
        join {{ source('vocab', 'concept') }} tc
          on tc.concept_id = cr.concept_id_2
         and tc.standard_concept = 'S'
         and tc.invalid_reason is null
        where cr.concept_id_1 = ws.source_concept_id
          and cr.relationship_id = 'Maps to'
          and cr.invalid_reason is null
    ) t on true
)

select
    fhir_system,
    code,
    display,
    vocabulary_id,
    coalesce(source_concept_id, 0)                         as source_concept_id,
    coalesce(target_concept_id, 0)                         as target_concept_id,
    target_domain_id,
    coalesce(n_targets, 0)::integer                        as n_targets,
    row_number() over (
        partition by fhir_system, code order by target_concept_id
    )::integer                                             as target_rank,
    case
        when vocabulary_id is null      then 'unknown_code_system'
        when source_concept_id is null  then 'code_not_in_vocabulary'
        when target_concept_id is null  then 'no_standard_mapping'
        else 'mapped'
    end                                                    as mapping_status
from with_targets
