-- End dates follow the OHDSI THEMIS convention (ADR-0007); the source has no quantity,
-- days supply or stop date:
--   written prescription        end = start + 29 days (a 30-day exposure)
--   administration/immunization end = start
-- days_supply stays NULL: the CDM says never to calculate it from other fields.
select
    row_number() over (order by event_id, concept_id)::integer  as drug_exposure_id,
    person_id::integer                                      as person_id,
    concept_id::integer                                     as drug_concept_id,
    start_datetime::date                                    as drug_exposure_start_date,
    start_datetime                                          as drug_exposure_start_datetime,
    case when record_kind = 'prescription'
         then start_datetime::date + ({{ var('prescription_days') }} - 1)
         else start_datetime::date
    end                                                     as drug_exposure_end_date,
    null::timestamp                                         as drug_exposure_end_datetime,
    null::date                                              as verbatim_end_date,
    case record_kind
        when 'prescription' then {{ var('type_ehr_prescription') }}
        when 'administration' then {{ var('type_ehr_administration') }}
        when 'immunization' then {{ var('type_ehr_administration') }}
        else {{ var('type_ehr') }}
    end::integer                                            as drug_type_concept_id,
    null::text                                              as stop_reason,
    null::integer                                           as refills,
    null::double precision                                  as quantity,
    null::integer                                           as days_supply,
    null::text                                              as sig,
    null::integer                                           as route_concept_id,
    null::text                                              as lot_number,
    null::integer                                           as provider_id,
    visit_occurrence_id::integer                            as visit_occurrence_id,
    null::integer                                           as visit_detail_id,
    source_code                                             as drug_source_value,
    source_concept_id::integer                              as drug_source_concept_id,
    null::text                                              as route_source_value,
    null::text                                              as dose_unit_source_value
from {{ ref('int_events_mapped') }}
where domain_id = 'Drug'
