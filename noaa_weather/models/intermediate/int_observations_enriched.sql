{{ config(materilized='view') }}

with observations as (
    select * from {{ ref('stg_observations') }}
),

target_stations as (
    select * from {{ ref('target_stations') }}
),

stations as (
    select * from {{ ref('stg_stations') }}
), 

filtered_observations as (
    select
        observations.*,
        target_stations.city
    
    from observations

    inner join target_stations
        on observations.station_id = target_stations.station_id
),

enriched as (
    select
        filtered_observations.*,
        stations.station_name,
        stations.latitude,
        stations.longitude,
        stations.elevation
    
    from filtered_observations

    inner join stations
        on filtered_observations.station_id = stations.station_id
),

final as (
    select
        *,
        quality_flag is not null as failed_quality_check
    
    from enriched
    
    where observation_date between '{{ var("start_date") }}' and '{{ var("end_date") }}'
)

select * from final