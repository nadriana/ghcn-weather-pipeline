{{ config(materilized='view') }}

with source as (
    select * from {{ source('raw', 'raw_country_codes') }}
),

renamed as (
    select
        trim(COUNTRY_CODE) as country_code,
        trim(COUNTRY_NAME) as country_name
    
    from source
)

select * from renamed