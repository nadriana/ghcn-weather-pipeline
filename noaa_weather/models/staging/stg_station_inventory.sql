{{ config(materilized='view') }}

with source as (
    select * from {{ source('raw', 'raw_station_inventory') }}
),

renamed as (
    select
        trim(ID) as station_id,
        LATITUDE as latitude,
        LONGITUDE as longitude,
        trim(ELEMENT) as element,
        FIRSTYEAR as first_year,
        LASTYEAR as last_year

    from source
)

select * from renamed