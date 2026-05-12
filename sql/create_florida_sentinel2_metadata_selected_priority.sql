DROP TABLE IF EXISTS public.florida_sentinel2_metadata_selected_priority;

CREATE TABLE public.florida_sentinel2_metadata_selected_priority AS
WITH ais_daily AS (
    SELECT
        DATE(timezone('UTC', "# Timestamp")) AS ais_date,
        COUNT(*) AS total_rows,
        COUNT(DISTINCT "MMSI") AS distinct_mmsi,
        COUNT(*) FILTER (
            WHERE CASE
                WHEN "Ship type" ~ '^[0-9]+(\.[0-9]+)?$'
                    THEN FLOOR(("Ship type")::numeric)::int BETWEEN 60 AND 69
                ELSE FALSE
            END
        ) AS passenger_rows,
        COUNT(*) FILTER (
            WHERE CASE
                WHEN "Ship type" ~ '^[0-9]+(\.[0-9]+)?$'
                    THEN FLOOR(("Ship type")::numeric)::int = 30
                ELSE FALSE
            END
        ) AS fishing_rows
    FROM public.ship_raw_data_florida_project_area
    GROUP BY 1
),
scene_daily AS (
    SELECT
        sm.*,
        DATE(timezone('UTC', sm.sensing_start)) AS sensing_date,
        COALESCE(ad.total_rows, 0) AS ais_total_rows,
        COALESCE(ad.distinct_mmsi, 0) AS ais_distinct_mmsi,
        COALESCE(ad.passenger_rows, 0) AS ais_passenger_rows,
        COALESCE(ad.fishing_rows, 0) AS ais_fishing_rows,
        COALESCE(ad.passenger_rows, 0) + COALESCE(ad.fishing_rows, 0) AS ais_target_rows
    FROM public.florida_sentinel2_metadata_selected sm
    LEFT JOIN ais_daily ad
      ON DATE(timezone('UTC', sm.sensing_start)) = ad.ais_date
),
threshold AS (
    SELECT percentile_disc(0.75) WITHIN GROUP (ORDER BY ais_target_rows) AS p75_target_rows
    FROM scene_daily
)
SELECT
    sd.*
FROM scene_daily sd
CROSS JOIN threshold t
WHERE sd.ais_target_rows >= t.p75_target_rows
ORDER BY
    sd.ais_target_rows DESC,
    sd.water_area DESC,
    sd.cloud_cover ASC,
    sd.sensing_start ASC;

CREATE INDEX IF NOT EXISTS florida_sentinel2_metadata_selected_priority_geom_idx
ON public.florida_sentinel2_metadata_selected_priority
USING GIST (geom);

CREATE INDEX IF NOT EXISTS florida_sentinel2_metadata_selected_priority_sensing_time_idx
ON public.florida_sentinel2_metadata_selected_priority (sensing_start);

CREATE INDEX IF NOT EXISTS florida_sentinel2_metadata_selected_priority_target_rows_idx
ON public.florida_sentinel2_metadata_selected_priority (ais_target_rows);

ANALYZE public.florida_sentinel2_metadata_selected_priority;
