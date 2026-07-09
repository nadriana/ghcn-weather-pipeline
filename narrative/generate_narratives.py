import os
import duckdb
import pandas as pd
from dotenv import load_dotenv
from google import genai

load_dotenv()

DUCKDB_PATH = "noaa_weather/dev.duckdb"
MODEL_NAME = "gemini-2.5-flash"

NON_ELEMENT_COLUMNS = {
    "station_id", "observation_date", "city", "station_name",
    "latitude", "longitude", "elevation"
}

Q = """
    select *
    from fct_daily_weather
    qualify row_number() over (partition by city order by observation_date desc) <= 7
    order by city, observation_date
"""

# DuckDB helpers
def fetch_recent_weather(db_path=DUCKDB_PATH):
    con = duckdb.connect(db_path)
    df = con.execute(Q).df()
    con.close
    return df

def load_narratives_to_duckdb(narratives_df, db_path=DUCKDB_PATH):
    con = duckdb.connect(db_path)
    con.execute("CREATE OR REPLACE TABLE narratives AS SELECT * FROM narratives_df")
    con.close()


# Tool definition
def get_element_definitions() -> str:
    elements_definition = """
        ACMC = Average cloudiness midnight to midnight from 30-second ceilometer data (percent)
        ACMH = Average cloudiness midnight to midnight from manual observations (percent)
        ADPT = Average dew point temperature for the day (tenths of degrees C)
        AWDR = Average daily wind direction (degrees)
        AWND = Average daily wind speed (tenths of meters per second)
        EVAP = Evaporation of water from evaporation pan (tenths of mm)
        PSUN = Daily percent of possible sunshine (percent)
        RHAV = Average relative humidity for the day (percent)
        TOBS = Temperature at time of observation (tenths of degrees C)
        WT01 = Fog, ice fog, or freezing fog
        WT03 = Thunder
        WT16 = Rain (may include freezing rain, drizzle, and freezing drizzle)
    """
    return elements_definition


# Promt
def build_prompt(row):
    core_elements = {"TMAX", "TMIN", "TAVG", "PRCP", "SNOW", "SNWD"}
    known_secondary_elements = {
        "WDFG": "Direction of peak wind gust (degrees)",
        "WSFG": "Peak gust wind speed (meters per second)",
        "TAVG": "Average daily temperature (°C)",
    }
 
    lines = []
    unknown_columns = []
 
    for column in row.index:
        if column in NON_ELEMENT_COLUMNS:
            continue
        value = row[column]
        value_text = "not available" if pd.isna(value) else str(value)
        lines.append(f"{column}: {value_text}")
 
        if column not in core_elements and column not in known_secondary_elements:
            unknown_columns.append(column)
 
    elements_text = "\n".join(lines)
 
    secondary_reference = "\n".join(
        f"{code} = {definition}" for code, definition in known_secondary_elements.items()
    )
 
    tool_note = (
        "All elements present in this data are defined above — no lookup needed."
        if not unknown_columns
        else f"The following element(s) are not defined above and are unfamiliar to you: "
             f"{', '.join(unknown_columns)}. Call the get_element_definitions tool to look up "
             f"what they mean before writing about them. Do not guess."
    )
 
    prompt = f"""You are a meteorologist writing a brief daily weather broadcast summary.
        Your response MUST begin with exactly this sentence, unchanged: "On {row['observation_date'].strftime('%B %d, %Y')}, in {row['city']}, the weather was as follows:"

        After that opening sentence, continue with temperature range, precipitation, and snowfall — these are the core elements. 
        Secondary elements (defined below, if present in the data) can be mentioned briefly afterward if relevant, but only if they can be phrased naturally
        — omit any secondary element rather than forcing an awkward or overly technical phrase (e.g. do not state raw wind direction in degrees; either describe it naturally or leave it out).

        The ideal narrative will be like this example:
            '
            [City], [Date] - Temperatures today ranged from a [temperature range]. The average temperature for the day was [average temperature]
            [6.8 mm] of precipitation, and there was no snowfall. 
            Peak wind gusts reaching 53.0 meters per second.
            '

        All values below are already in standard real-world units (not raw/scaled) — use them exactly as given.
        
        Core elements:
            TMAX (max temp, °C)
            TMIN (min temp, °C)
            PRCP (precipitation, mm)
            SNOW (snowfall, mm)
            SNWD (snow depth, mm)
        
        Known secondary elements:
        {secondary_reference}
        
        {tool_note}
        
        Do not invent any numbers not provided. If a core element is unavailable, say so plainly.
        
        City: {row['city']}
        Date: {row['observation_date']}
        {elements_text}
    """
    return prompt



# Gemini call
def generate_narrative(client, prompt):
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config={"tools": [get_element_definitions]},
    )
    return response.text



# Run pipeline
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
 
    df = fetch_recent_weather()
 
    results = []
    for _, row in df.iterrows():
        prompt = build_prompt(row)
        narrative = generate_narrative(client, prompt)
        print(f"{row['city']} — {row['observation_date']}: {narrative[:80]}...")
        results.append({
            "station_id": row["station_id"],
            "city": row["city"],
            "observation_date": row["observation_date"],
            "narrative": narrative,
        })
 
    narratives_df = pd.DataFrame(results)
    load_narratives_to_duckdb(narratives_df)
    print(f"\nSaved {len(narratives_df)} narratives to DuckDB table 'narratives'.")
 
 
if __name__ == "__main__":
    main()