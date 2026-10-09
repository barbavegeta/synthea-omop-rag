select
    1::integer as cohort_definition_id,
    'Incident type 2 diabetes'::text as cohort_definition_name,
    'First-ever T2DM record (with descendants) as index; index in observation period; '
    || 'aged >= 18; >= 1 visit in the 365 days before index; no type 1 diabetes on or '
    || 'before index. Exit at end of observation or death. See ADR-0010.'::text
        as cohort_definition_description
