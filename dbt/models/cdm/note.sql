-- CDM NOTE: the synthetic notes generated in Phase 4 (rwe notes), with the visit-kind
-- specific type concept, LOINC "Progress note" as class, UTF-8 and English.
select
    n.note_id::integer                                     as note_id,
    n.person_id::integer                                   as person_id,
    n.note_date                                            as note_date,
    n.note_date::timestamp                                 as note_datetime,
    case n.note_kind
        when 'Outpatient'     then {{ var('type_ehr_outpatient_note') }}
        when 'Emergency Room' then {{ var('type_ehr_er_note') }}
        when 'Inpatient'      then {{ var('type_ehr_inpatient_note') }}
        else {{ var('type_ehr_note') }}
    end::integer                                           as note_type_concept_id,
    {{ var('note_class_progress_note') }}::integer         as note_class_concept_id,
    n.note_title                                           as note_title,
    n.note_text                                            as note_text,
    {{ var('encoding_utf8') }}::integer                    as encoding_concept_id,
    {{ var('language_english') }}::integer                 as language_concept_id,
    null::integer                                          as provider_id,
    n.visit_occurrence_id::integer                         as visit_occurrence_id,
    null::integer                                          as visit_detail_id,
    'synthetic template note (Phase 4)'::text              as note_source_value,
    null::integer                                          as note_event_id,
    null::integer                                          as note_event_field_concept_id
from {{ source('notes', 'generated_note') }} n
