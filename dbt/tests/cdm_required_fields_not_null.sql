-- Every field the v5.4 spec marks as required must be populated in every row.
-- The list of required fields is read from the spec seed at run time.
-- depends_on: {{ ref('person') }}, {{ ref('observation_period') }}, {{ ref('visit_occurrence') }}
-- depends_on: {{ ref('condition_occurrence') }}, {{ ref('drug_exposure') }}, {{ ref('procedure_occurrence') }}
-- depends_on: {{ ref('measurement') }}, {{ ref('observation') }}, {{ ref('death') }}, {{ ref('cdm_source') }}, {{ ref('note') }}
-- depends_on: {{ ref('cdm_v54_fields') }}
{% set required = [] %}
{% if execute %}
    {% set query %}
        select cdm_table, cdm_field from {{ ref('cdm_v54_fields') }}
        where is_required order by cdm_table, field_order
    {% endset %}
    {% set required = run_query(query).rows %}
{% endif %}

{% set schema = ref('person').schema %}
{% for row in required %}
select '{{ row[0] }}.{{ row[1] }}' as required_field, count(*) as null_rows
from {{ schema }}.{{ row[0] }}
where {{ row[1] }} is null
having count(*) > 0
{% if not loop.last %}union all{% endif %}
{% endfor %}
{% if required | length == 0 %}
select null::text as required_field, 0 as null_rows where false
{% endif %}
