# GHCN Weather Pipeline

A local data pipeline that ingests NOAA's Global Historical Climatology Network (GHCN) daily
weather data for airport stations in Canada's five largest metropolitan areas, transforms it
through a layered dbt project, and generates AI-powered daily weather narratives using Google
Gemini — with an LLM-based validation guardrail that fact-checks each narrative against its
source data before it's saved.

**Target stations:** Toronto Pearson Intl, Montreal Intl (Trudeau), Vancouver Intl (YVR),
Calgary Intl (YYC), Ottawa Macdonald-Cartier Intl.

---

## Architecture Overview

```
NOAA GHCN-Daily (https://www.ncei.noaa.gov/pub/data/ghcn/daily/)
        │
        ▼
  ingestion/ingest.py  ──────────────►  DuckDB: raw_* tables
        │                                (untouched, as NOAA published them)
        ▼
  dbt seed (target_stations.csv) ────►  DuckDB: target_stations table
        │
        ▼
  dbt staging layer  ─────────────────► stg_observations, stg_stations,
        │                                stg_station_inventory, stg_country_codes
        │                                (renamed, typed, scaled — one model per source,
        │                                 no joins, no filtering)
        ▼
  dbt intermediate layer  ────────────► int_observations_enriched
        │                                (joined to station metadata, filtered to target
        │                                 stations + date range, quality-flagged)
        ▼
  dbt marts layer  ───────────────────► fct_daily_weather
        │                                (pivoted wide: one row per station-date,
        │                                 one column per element, quality-filtered,
        │                                 tested)
        ▼
  narrative/generate_narratives.py  ──► Gemini generates a narrative per station-day
        │                                (dynamic element handling, tool-calling fallback
        │                                 for unrecognized element codes, retry on
        │                                 transient API errors)
        ▼
  narrative/guardrail/validator.py  ──► A second Gemini call fact-checks each narrative
        │                                against its source row before saving
        ▼
  DuckDB: narratives table               (narrative text + is_valid + invalid_reason)
```

**Why this layering?** Each stage has one job:
- **Raw** = a faithful, untouched mirror of what NOAA published (no header row, no renaming,
  no scaling). If something looks wrong downstream, raw tables let you confirm whether NOAA's
  source data or a later transformation step is responsible.
- **Staging** = one model per raw source, doing only renaming, type casting, and unit scaling
  (e.g. converting GHCN's "tenths of °C" into actual °C). No joins, no business filtering.
- **Intermediate** = where sources get joined together and business logic (which stations,
  which date range, which quality flags) gets applied.
- **Marts** = the final, analysis-ready shape — one row per station-date, ready for
  consumption by the narrative generator or any other downstream user.
- **Narrative + validation** = a two-model pattern: one Gemini call writes the narrative, a
  second, independent Gemini call checks it against the source row before it's trusted.

---

## Setup Instructions

### Prerequisites
- Python 3.11+ and `pip`
- A [Google Gemini API key](https://aistudio.google.com/apikey) (free tier)

### 1. Clone and set up the environment

```bash
git clone https://github.com/nadriana/ghcn-weather-pipeline.git
cd ghcn-weather-pipeline

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Add your Gemini API key

Create a `.env` file in the repo root:

```
GEMINI_API_KEY=your_key_here
```

### 3. Ingest raw data

Run from the **repo root**. This downloads daily observations for the 5 target stations plus
all reference/metadata files directly from NOAA, and loads them into DuckDB as untouched raw
tables.

```bash
python3 ingestion/ingest.py
```

### 4. Run the dbt project

All `dbt` commands run from the `noaa_weather/` subdirectory.

```bash
cd noaa_weather
dbt deps      # installs dbt_utils package
dbt seed      # loads seeds/target_stations.csv into DuckDB
dbt run       # builds staging, intermediate, and marts layers
dbt test      # runs data quality tests against the marts layer
```

### 5. Generate and validate narratives

Run from the **repo root**.

```bash
cd ..
python3 narrative/generate_narratives.py
```

This generates weather narratives for the most recent 7 days per city (35 narratives total),
fact-checks each one against its source row via a second Gemini call, and saves everything —
narrative text plus `is_valid`/`invalid_reason` — to a `narratives` table in DuckDB.

### 6. Explore the results

```bash
cd noaa_weather
duckdb dev.duckdb -ui
```

Opens a local browser UI for querying any table, including `fct_daily_weather` and
`narratives`.

---

## Design Decisions

### Station and element selection — config-driven, not hardcoded

The 5 target stations live in a single source of truth: `noaa_weather/seeds/target_stations.csv`,
loaded via `dbt seed`. Both the ingestion script and every dbt model that needs to filter to
target stations reference this same table — there is no station ID hardcoded anywhere in SQL.
**Adding a 6th city means adding one row to this CSV — no code or SQL changes required.**

Element handling is fully dynamic. Rather than hardcoding column names like `TMAX`/`TMIN`/`PRCP`
in the mart, `fct_daily_weather` uses `dbt_utils.pivot()` combined with
`dbt_utils.get_column_values()`, which queries the actual distinct element codes present in the
data **at compile time** and generates the pivot columns automatically. If a 6th station reports
an element none of the current 5 stations report, it will appear as a new column automatically
on the next `dbt run`, with no SQL changes.

The narrative generation script mirrors this principle: `build_prompt()` iterates over whatever
element columns are present in a row, rather than referencing specific element names. Elements
outside a small, pre-defined "core + known secondary" set trigger a tool call
(`get_element_definitions`) that the LLM can use to look up an unfamiliar element code before
writing about it, rather than guessing. This tool is not exercised by the current 5-station
dataset (all their elements are pre-defined in the prompt) but is architecturally in place for
extensibility.

### Unit scaling

NOAA stores several elements (temperature, precipitation, wind speed, etc.) as integers scaled
by 10 (e.g. `TMAX = 227` means 22.7°C). This scaling is applied in the staging layer
(`stg_observations.sql`) via a `CASE WHEN` covering the 5 elements actually present in this
dataset (`TMAX`, `TMIN`, `TAVG`, `PRCP`, `WSFG`). A more complete solution — covering GHCN's
full ~40-element universe, including wildcard-pattern soil temperature codes — would use a
small seed file mapping element code to scale factor, joined in rather than hardcoded. This was
deferred as out of scope for the current 5-station dataset (see Tradeoffs below).

### Data quality: QFLAG handling

NOAA marks each observation with a quality flag (`QFLAG`) when it fails one of NOAA's own
quality assurance checks. Within the scoped date range (2 years × 5 stations, ~24,300 rows),
only 8 rows carry a non-null QFLAG (~0.03%).

- **`int_observations_enriched`** keeps every row, including flagged ones, and adds an explicit
  `failed_quality_check` boolean column. This preserves full traceability — nothing is silently
  discarded at this layer, and the specific QFLAG code (e.g. `I` = failed internal consistency
  check, `X` = failed bounds check) remains queryable.
- **`fct_daily_weather`** filters out any row where `failed_quality_check = true`. Because the
  mart is pivoted (multiple elements collapsed into one row per station-date), there's no way to
  indicate *which* element failed without either losing that specificity or adding a flag column
  per element. Given the negligible data loss, excluding flagged rows entirely from the mart
  was the simpler, safer choice for downstream narrative generation — avoiding a scenario where
  an LLM confidently narrates a temperature reading NOAA itself flagged as suspect.

### Date range scoping

Scoped to a 2-year window: 2022-04-28 to 2024-04-28, configured via dbt `vars` in
`dbt_project.yml` rather than hardcoded in SQL. The end date was chosen as the latest date with
complete data across **all 5 stations** (Vancouver's data extends further, to 2025-08-24, but
using a per-station "most recent 2 years" would produce non-overlapping windows across cities,
making cross-city comparison meaningless).

### Narrative generation

Narratives are generated per station-day for the 7 most recent days per city (35 total), as a
demonstration of bulk generation within a reasonable API call budget. Each narrative:
- Is required to begin with a fixed opening sentence structure, enforced in the prompt, so every
  narrative has a consistent, predictable format rather than varying wildly call to call.
- Is instructed to omit secondary elements (like wind direction in degrees) rather than force
  them into awkward, overly technical phrasing.
- Is generated by a model given only pre-scaled, real-world-unit values, with explicit
  instruction not to invent numbers or re-scale anything.

### Validation guardrail

Each generated narrative is checked by a second, independent Gemini call
(`narrative/guardrail/validator.py`) that compares the narrative's stated facts against the
original source row and returns a structured `is_valid` / `invalid_reason` verdict, saved
alongside the narrative in DuckDB. This has demonstrably caught real hallucinations during
development — for example, a narrative that stated a wind gust speed not present in the source
data. See Tradeoffs below for a known limitation of this guardrail.

### Data quality checks performed

- **Date coverage**: confirmed all 5 stations report 731–732 of ~731 expected days in the scoped
  window (near-complete coverage, no meaningful gaps).
- **QFLAG audit**: confirmed only 8 of ~24,300 rows failed NOAA's own quality checks (see above).
- **Automated dbt tests** on `fct_daily_weather`: `not_null` on key columns, `accepted_values`
  on `city` (flagged in the test itself as scoped to the initial 5 cities — a known,
  intentionally temporary hardcode, not a business rule), and
  `dbt_utils.unique_combination_of_columns` on `station_id` + `observation_date`, confirming the
  pivot produces no duplicate rows.
- **Reproducibility test**: the full pipeline (ingestion → dbt → narratives) was run from a
  completely deleted database to confirm it rebuilds cleanly end-to-end. This caught a real bug
  — a typo in a column name (`failled_quality_check` vs. `failed_quality_check`) that had gone
  unnoticed because a stale, previously-built database was masking it. Fixed and verified before
  submission.

---

## Tradeoffs & What I'd Improve With More Time

- **Unit scaling coverage**: currently hardcodes the 5 elements known to appear in this dataset.
  A more robust version would use a dbt seed mapping every GHCN element code to its scale
  factor, joined in dynamically — necessary if a future station reports an element outside this
  list.
- **QFLAG granularity in the mart**: flagged rows are excluded entirely from `fct_daily_weather`
  rather than preserved with per-element flag columns. Full traceability still exists one layer
  up in `int_observations_enriched`.
- **Narrative consistency**: minor phrasing (e.g. tense) still varies slightly call-to-call
  despite a fixed opening sentence enforced in the prompt — inherent LLM non-determinism. Lower
  `temperature` generation settings could tighten this further.
- **Validation guardrail precision**: the guardrail occasionally flags narratives as invalid due
  to overly strict interpretation (e.g., minor rounding or phrasing differences). A future
  iteration would tune the validation prompt's tolerance, or add a secondary review step before treating `is_valid = false` as a hard signal.
- **Narrative scale**: the current run generates 35 narratives (7 most recent days × 5 cities).
  The pipeline is trivially extendable to the full ~24K row mart by removing the
  `qualify row_number()` limit in the narrative query — deferred here to stay within a
  reasonable API call budget and iteration time.
- **Orchestration**: Scripts are run manually in sequence per the setup instructions above.
- **Incremental dbt models**: all models currently do a full rebuild on every `dbt run`. For a
  larger date range or more frequent runs, incremental materialization would meaningfully
  reduce build time.
- **API resilience**: narrative and validation calls include retry logic for transient errors
  (e.g. `503 UNAVAILABLE` under high demand), but a single row's failure after all retries is
  currently logged and skipped rather than retried in a later pass.

---

## Repository Structure

```
ghcn-weather-pipeline/
├── ingestion/
│   └── ingest.py                     # Pulls raw NOAA files into DuckDB, untransformed
├── noaa_weather/                     # dbt project
│   ├── seeds/
│   │   └── target_stations.csv       # Single source of truth for target stations
│   ├── models/
│   │   ├── staging/                   # One model per raw source: rename, type, scale
│   │   ├── intermediate/              # Joins, filtering, quality flagging
│   │   └── marts/                     # Final pivoted, quality-filtered, tested output
│   └── dbt_project.yml                # Includes date-range vars
├── narrative/
│   ├── generate_narratives.py        # Gemini-powered narrative generation
│   └── guardrail/
│       └── validator.py               # Fact-checks narratives against source data
├── data_exploration/
│   └── exploration.ipynb             # Early exploratory notebook (kept for process visibility)
└── requirements.txt
```
