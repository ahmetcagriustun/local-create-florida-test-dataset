# Local Create Florida Test Dataset

This repository contains the local-first workflow used to construct the South Florida AIS/Sentinel-2 external test dataset for the manuscript revision experiments.

It covers NOAA AIS download and filtering, PostgreSQL/PostGIS staging, Sentinel-2 metadata selection, local Sentinel-2 download indexing, temporal AIS-image matching, and patch-generation support for the Florida project area.

The current default setup is:

- project-area source: `public.florida_project_area`
- Sentinel-2 metadata table: `public.florida_sentinel2_metadata`
- selected-scene table: `public.florida_sentinel2_metadata_selected`
- date range: `2023-01-01` to `2023-06-30`

## Why this region

This project area was designed for the paper revision's external-region experiments and can be updated as the Florida AOI evolves.

## Repository goal

The aim is not to replace the original Danish AIS pipeline.

Instead, this repo isolates the external-region data acquisition and patch-generation stage so it can be pushed to GitHub as a clean, standalone workflow.

## What this repo does

1. Builds the expected NOAA bulk file list for the configured date range.
2. Downloads daily NOAA AIS files to local storage.
3. Filters those files to the configured bbox or project-area polygon.
4. Keeps only the paper's target vessel-type codes if desired.
5. Merges the filtered daily files into one analysis-ready CSV.
6. Optionally imports the merged file into PostgreSQL/PostGIS.
7. Fetches Sentinel-2 metadata for the same AOI and date window into PostgreSQL.
8. Downloads the selected Sentinel-2 products locally from CDSE.
9. Builds Florida-specific Sentinel-2 download index tables in PostgreSQL.
10. Imports only the Florida project-area AIS records for the selected Sentinel-2 dates into PostgreSQL.
11. Builds Florida-prefixed PostgreSQL tables for temporal matching and patch generation.

## Directory layout

```text
local-create-florida-test-dataset/
  main.py
  config.example.yaml
  requirements.txt
  README.md
  noaa_pipeline/
  scripts/
  docs/
  data/
```

## Install

```bash
pip install -r requirements.txt
```

## Main commands

Preview the expected NOAA daily files:

```bash
python main.py --config config.example.yaml plan-download
```

Download the raw NOAA `.csv.zst` files:

```bash
python main.py --config config.example.yaml download
```

Filter raw files to the configured AOI:

```bash
python main.py --config config.example.yaml filter-aoi
```

Merge daily filtered files:

```bash
python main.py --config config.example.yaml merge-filtered
```

Import the merged file into PostgreSQL:

```bash
python main.py --config config.example.yaml import-postgres
```

Fetch Sentinel-2 metadata into PostgreSQL:

```bash
python main.py --config config.local.yaml fetch-s2-metadata --truncate
```

Estimate the selected Sentinel-2 download volume:

```bash
python main.py --config config.local.yaml estimate-s2-download
```

Download the selected Sentinel-2 products locally:

```bash
python main.py --config config.local.yaml download-s2-selected
```

Build the Florida Sentinel-2 download index table:

```bash
python main.py --config config.local.yaml build-s2-download-index --truncate
```

Build the Florida Sentinel-2 geometry index table:

```bash
python main.py --config config.local.yaml build-s2-download-index-geom
```

Import only the Florida AIS records for the selected Sentinel-2 dates:

```bash
python main.py --config config.local.yaml import-ship-raw-florida --truncate
```

## Notes on source data

This repo is built around NOAA bulk AIS point files, not AccessAIS order links.

That choice is deliberate because NOAA's AccessAIS tool is better suited to small, interactive exports, while this workflow needs reproducible bulk downloads across a block date range.

## Sentinel-2 metadata source

Sentinel-2 metadata search in this repo uses the Copernicus Data Space Ecosystem OData catalogue.

This search step does not require Sentinel Hub OAuth client credentials. The code performs catalogue queries and writes the returned metadata to PostgreSQL. CDSE credentials are only needed later if full product downloads are required.

## Expected storage behavior

The final filtered data volume may be modest, but the raw daily files are large.

For the current Florida `2023-01-01` to `2023-06-30` window, expect the raw download stage to be much heavier than the final filtered subset.

## Existing helper scripts

- `scripts/inspect_accessais_csv.py`
- `scripts/normalize_accessais_csv.py`

These are still useful for ad hoc inspection of NOAA CSV files and schema checks.
