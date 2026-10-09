{#
  dbt's default prefixes custom schemas with the target schema (dbt_cdm, dbt_stg, ...).
  Use the custom name as-is so the CDM lives in a schema literally called `cdm`.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
