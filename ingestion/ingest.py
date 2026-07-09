import pandas as pd
import duckdb

# Configuration file
CONFIG_PATH = "noaa_weather/seeds/target_stations.csv"

# NOAA
BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
# Daily observations by stations
DAILY_OBS = "by_station/"
# Metadata files
STATION_METADATA = "ghcnd-stations.txt"
STATION_INVENTORY = "ghcnd-inventory.txt"
COUNTRY_CODES = "ghcnd-countries.txt"

# DuckDB
DUCKDB_PATH = "noaa_weather/dev.duckdb"


# Stations data
def load_target_stations(config_path=CONFIG_PATH):
    df = pd.read_csv(config_path)
    
    return df.to_dict(orient='records')


# Fetch daily raw data from NOAA weather
def fetch_station_data(station_id, base_url=BASE_URL, daily_obs=DAILY_OBS):    
    STATION_URL = f"{base_url}{daily_obs}{station_id}.csv.gz" 
    df = pd.read_csv(STATION_URL, compression="gzip", header=None, dtype=str)
    
    return df


# Fetch raw data from all target cities and combine them into a sigle df
def fetch_all_stations_data(stations):
    station_data_list = []
    for i in range(len(stations)):
        station_data_list.append(fetch_station_data(station_id=stations[i]["station_id"]))

    df = pd.concat(station_data_list, ignore_index=True)
    
    return df


# Metadata
def fetch_fixed_widht_file(file, colspecs, names, base_url=BASE_URL):
    df = pd.read_fwf(f"{base_url}{file}", colspecs=colspecs, names=names, header=None)
    return df


# Write to DuckDB
def load_to_duckdb(df, table_name, duckdb_path = DUCKDB_PATH):
    con = duckdb.connect(duckdb_path)
    con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df")
    con.close()


# Run ingestion
def main():
    # Load daily observations
    stations = load_target_stations(config_path=CONFIG_PATH)
    df = fetch_all_stations_data(stations)
    print(f"raw_daily_observations: {df.shape}")
    load_to_duckdb(df, table_name="raw_daily_observations", duckdb_path = DUCKDB_PATH)

    # Load metadata
    station_metadata_df = fetch_fixed_widht_file(
        file=STATION_METADATA, 
        colspecs=[(0,11), (12,20), (21,30), (31,37), (38,40), (41,71), (72,75), (77,79), (80,85)],
        names=["ID", "LATITUDE", "LONGITUDE", "ELEVATION", "STATE", "NAME", "GSN_FLAG", "HCN_CRN_FLAG", "WMO_ID"],
        base_url=BASE_URL
        )
    print(f"raw_station_metadata: {station_metadata_df.shape}")
    load_to_duckdb(station_metadata_df, table_name="raw_station_metadata", duckdb_path = DUCKDB_PATH)

    station_inventory_df = fetch_fixed_widht_file(
        file=STATION_INVENTORY, 
        colspecs=[(0,11), (12,20), (21,30), (31,35), (36,40), (41,45)],
        names=["ID", "LATITUDE", "LONGITUDE", "ELEMENT", "FIRSTYEAR", "LASTYEAR"], 
        base_url=BASE_URL
        )
    print(f"raw_station_inventory: {station_inventory_df.shape}")
    load_to_duckdb(station_inventory_df, table_name="raw_station_inventory", duckdb_path = DUCKDB_PATH)

    country_codes_df = fetch_fixed_widht_file(
        file=COUNTRY_CODES, 
        colspecs=[(0,2), (2,None)],
        names=["COUNTRY_CODE", "COUNTRY_NAME"], 
        base_url=BASE_URL
        )
    print(f"raw_country_codes: {country_codes_df.shape}")
    load_to_duckdb(country_codes_df, table_name="raw_country_codes", duckdb_path = DUCKDB_PATH)


if __name__ == "__main__":
    main()
    