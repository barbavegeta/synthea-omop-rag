-- The concept ids hard-coded as dbt vars must exist in the loaded vocabulary, with the
-- expected name and vocabulary. A typo in an id fails here instead of silently
-- mislabelling every record.
with expected (concept_id, concept_name, vocabulary_id) as (
    values
        ({{ var('type_ehr') }},                'EHR',                       'Type Concept'),
        ({{ var('type_ehr_prescription') }},   'EHR prescription',          'Type Concept'),
        ({{ var('type_ehr_administration') }}, 'EHR administration record', 'Type Concept'),
        ({{ var('type_ehr_note') }},           'EHR note',                  'Type Concept'),
        ({{ var('type_ehr_outpatient_note') }},'EHR outpatient note',       'Type Concept'),
        ({{ var('type_ehr_er_note') }},        'EHR emergency room note',   'Type Concept'),
        ({{ var('type_ehr_inpatient_note') }}, 'EHR inpatient note',        'Type Concept'),
        ({{ var('note_class_progress_note') }},'Progress note',             'LOINC'),
        ({{ var('encoding_utf8') }},           'UTF-8',                     'Metadata'),
        ({{ var('language_english') }},        'English language',          'SNOMED')
)

select e.*
from expected e
left join {{ source('vocab', 'concept') }} c
       on c.concept_id = e.concept_id
      and c.concept_name = e.concept_name
      and c.vocabulary_id = e.vocabulary_id
where c.concept_id is null
