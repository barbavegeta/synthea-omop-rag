-- Concept sets expanded to concept ids: each seed entry (vocabulary code + whether to
-- include descendants) resolved through CONCEPT, then CONCEPT_ANCESTOR. This is what an
-- ATLAS concept set does: "type 2 diabetes and everything more specific beneath it".
with entries as (
    select s.concept_set, s.include_descendants, c.concept_id
    from {{ ref('concept_sets') }} s
    join {{ source('vocab', 'concept') }} c
      on c.vocabulary_id = s.vocabulary_id and c.concept_code = s.concept_code
)

select distinct e.concept_set, ca.descendant_concept_id as concept_id
from entries e
join {{ source('vocab', 'concept_ancestor') }} ca on ca.ancestor_concept_id = e.concept_id
where e.include_descendants

union

select concept_set, concept_id
from entries
