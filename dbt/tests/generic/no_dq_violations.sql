{# Fails (or warns) when dq_violations has any row for the given check. #}
{% test no_dq_violations(model, check_name) %}
    select * from {{ model }} where check_name = '{{ check_name }}'
{% endtest %}
