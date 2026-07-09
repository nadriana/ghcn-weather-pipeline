{{ config(materilized='view') }}

with source as (
    select * from {{ source("raw", "raw_station_metadata") }}
),

renamed as (
    select
        trim(ID) as station_id,
        LATITUDE as latitude,
        LONGITUDE as longitude,
        ELEVATION as elevation,
        trim(STATE) as state,
        trim(NAME) as station_name,
        trim(GSN_FLAG) as gsn_flag,
        trim(HCN_CRN_FLAG) as hcn_crn_flag,
        trim(cast(WMO_ID as varchar)) as wmo_id

    from source
)

select * from renamed
