-- Every CDM table must match the official OMOP CDM v5.4 field list (seed cdm_v54_fields,
-- generated from OHDSI/CommonDataModel): same columns, same order, compatible types.
-- Returns one row per problem.
-- depends_on: {{ ref('person') }}, {{ ref('observation_period') }}, {{ ref('visit_occurrence') }}
-- depends_on: {{ ref('condition_occurrence') }}, {{ ref('drug_exposure') }}, {{ ref('procedure_occurrence') }}
-- depends_on: {{ ref('measurement') }}, {{ ref('observation') }}, {{ ref('death') }}, {{ ref('cdm_source') }}, {{ ref('note') }}
with spec as (
    select cdm_table, cdm_field, field_order, cdm_datatype
    from {{ ref('cdm_v54_fields') }}
),

actual as (
    select table_name::text as cdm_table, column_name::text as cdm_field,
           ordinal_position as field_order, data_type::text as data_type
    from information_schema.columns
    where table_schema = '{{ ref("person").schema }}'
      and table_name in (select cdm_table from spec)
),

compared as (
    select
        coalesce(s.cdm_table, a.cdm_table) as cdm_table,
        coalesce(s.cdm_field, a.cdm_field) as cdm_field,
        s.cdm_datatype, a.data_type, s.field_order as spec_order, a.field_order as actual_order,
        case
            when s.cdm_datatype = 'integer'      then a.data_type = 'integer'
            when s.cdm_datatype = 'bigint'       then a.data_type in ('bigint', 'integer')
            when s.cdm_datatype = 'date'         then a.data_type = 'date'
            when s.cdm_datatype = 'datetime'     then a.data_type like 'timestamp%'
            when s.cdm_datatype = 'float'        then a.data_type in ('double precision', 'numeric', 'real')
            when s.cdm_datatype like 'varchar%'  then a.data_type in ('text', 'character varying')
        end as type_ok
    from spec s
    full join actual a on a.cdm_table = s.cdm_table and a.cdm_field = s.cdm_field
)

select cdm_table, cdm_field,
       case
           when data_type is null    then 'missing column'
           when cdm_datatype is null then 'column not in v5.4 spec'
           when spec_order <> actual_order then 'position ' || actual_order || ', spec ' || spec_order
           when not coalesce(type_ok, false) then 'type ' || data_type || ', spec ' || cdm_datatype
       end as problem
from compared
where data_type is null
   or cdm_datatype is null
   or spec_order <> actual_order
   or not coalesce(type_ok, false)
