-- Every concept-set entry must resolve to a concept in the loaded vocabulary, so a
-- mistyped code fails the build instead of silently shrinking a cohort or covariate.
-- Skipped on the CI stub vocabulary, which contains only codes present in the fixture.
select s.*
from {{ ref('concept_sets') }} s
left join {{ source('vocab', 'concept') }} c
       on c.vocabulary_id = s.vocabulary_id and c.concept_code = s.concept_code
where c.concept_id is null
  and not exists (
      select 1 from {{ source('vocab', 'vocabulary') }}
      where vocabulary_id = 'None' and vocabulary_version like 'STUB%'
  )
