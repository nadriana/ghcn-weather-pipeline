{{ config(materialized='table') }}

with observations as (
    select * 
    from {{ ref('int_observations_enriched') }}
    where failed_quality_check = false
),

pivoted as (
    select
        station_id,
        observation_date,
        city,
        station_name,
        latitude,
        longitude,
        elevation,
        {{ dbt_utils.pivot(
            column='element',
            values=dbt_utils.get_column_values(
                table=ref('int_observations_enriched'),
                column='element'
            ),
            agg='max',
            then_value='observation_value',
            else_value='null'
        ) }}

    from observations

    group by station_id, observation_date, city, station_name, latitude, longitude, elevation
)

select * from pivoted