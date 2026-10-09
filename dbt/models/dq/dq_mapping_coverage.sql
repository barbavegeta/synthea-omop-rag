-- Concept-mapping coverage per target CDM table: the share of records, and of distinct
-- source codes, that reached a standard concept (concept_id <> 0). Domains with no table
-- in this CDM subset are listed as dropped rather than silently disappearing.
select
    case domain_id
        when 'Condition'   then 'condition_occurrence'
        when 'Drug'        then 'drug_exposure'
        when 'Procedure'   then 'procedure_occurrence'
        when 'Measurement' then 'measurement'
        when 'Observation' then 'observation'
        else '(dropped: ' || domain_id || ' domain has no table)'
    end                                                          as cdm_table,
    count(*)                                                     as records,
    count(*) filter (where concept_id <> 0)                      as records_mapped,
    round(100.0 * count(*) filter (where concept_id <> 0) / count(*), 2)
                                                                 as pct_records_mapped,
    count(distinct (fhir_system, source_code))                   as source_codes,
    count(distinct (fhir_system, source_code)) filter (where concept_id <> 0)
                                                                 as source_codes_mapped,
    round(100.0 * count(distinct (fhir_system, source_code)) filter (where concept_id <> 0)
          / nullif(count(distinct (fhir_system, source_code)), 0), 2)
                                                                 as pct_codes_mapped
from {{ ref('int_events_mapped') }}
group by 1
