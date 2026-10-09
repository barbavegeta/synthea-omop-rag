{# Helpers for reading FHIR JSON in staging models. #}

{# 'urn:uuid:abc' -> 'abc'. Transaction bundles reference other entries by urn:uuid. #}
{% macro fhir_ref(expr) -%}
    regexp_replace({{ expr }}, '^urn:uuid:', '')
{%- endmacro %}

{#
  FHIR dateTime text -> timestamp in UTC. Explicit AT TIME ZONE so the result never
  depends on the database session's TimeZone setting.
#}
{% macro fhir_ts(expr) -%}
    (({{ expr }})::timestamptz at time zone 'UTC')
{%- endmacro %}

{# A FHIR CodeableConcept -> jsonb array of {system, code, display}, order preserved. #}
{% macro fhir_codings(expr) -%}
    coalesce({{ expr }} -> 'coding', '[]'::jsonb)
{%- endmacro %}
