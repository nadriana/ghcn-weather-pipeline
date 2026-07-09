{{ config(materilized='view') }}

with source as (
    select * from {{ source('raw', 'raw_daily_observations') }}
),

renamed as (
    select
        "0" as station_id,
        cast(strptime("1", '%Y%m%d') as date) as observation_date,
        "2" as element,
        case
            when "2" in ('TMAX', 'TMIN', 'PRCP', 'TAVG', 'WSFG')
                then cast("3" as integer) / 10.0
            else cast("3" as integer)
        end as observation_value,
        "4" as measurement_flag,
        "5" as quality_flag,
        "6" as source_flag,
        "7" as observation_time

    from source
)

select * from renamed