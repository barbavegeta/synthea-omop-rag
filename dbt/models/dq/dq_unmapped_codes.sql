-- Every source code that did not reach a standard concept, with why and how often.
-- This is the work list a real ETL team would triage (e.g. request a local mapping).
select
    domain_id,
    fhir_system,
    source_code,
    mapping_status,
    max(code_text)  as example_text,
    count(*)        as records
from {{ ref('int_events_mapped') }}
where concept_id = 0
group by 1, 2, 3, 4
