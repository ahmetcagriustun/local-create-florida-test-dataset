SELECT
    COUNT(*) AS row_count,
    COUNT(DISTINCT "MMSI") AS distinct_mmsi,
    MIN("# Timestamp") AS min_ts,
    MAX("# Timestamp") AS max_ts
FROM public.ship_raw_data_florida_project_area;

SELECT
    pg_size_pretty(pg_total_relation_size('public.ship_raw_data_florida_project_area')) AS total_size;
