SET work_mem = '512MB';
SET maintenance_work_mem = '1GB';
SET max_parallel_workers_per_gather = 4;
SET max_parallel_workers = 16;

DROP TABLE IF EXISTS public.florida_closest_mmsi_timestamps;

CREATE TABLE public.florida_closest_mmsi_timestamps AS
WITH closest_timestamps AS (
    SELECT
        sr.*,
        sdi.sensing_time_without_tz,
        sdi.api_id,
        CASE
            WHEN sr."# Timestamp" <= sdi.sensing_time_without_tz THEN 'before'
            WHEN sr."# Timestamp" >  sdi.sensing_time_without_tz THEN 'after'
        END AS time_relation,
        ABS(EXTRACT(EPOCH FROM (sr."# Timestamp" - sdi.sensing_time_without_tz))) AS time_diff
    FROM public.florida_ship_raw_data sr
    JOIN public.florida_sentinel2_download_index_geom sdi
      ON sr."# Timestamp" BETWEEN sdi.sensing_time_without_tz - INTERVAL '10 minutes'
                              AND sdi.sensing_time_without_tz + INTERVAL '10 minutes'
     AND ST_Intersects(sr.geom, sdi.geom_4326)
),
ranked_timestamps AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY "MMSI", api_id, sensing_time_without_tz, time_relation
            ORDER BY time_diff ASC
        ) AS rank
    FROM closest_timestamps
)
SELECT *
FROM ranked_timestamps
WHERE rank = 1
  AND time_relation IS NOT NULL;

CREATE INDEX IF NOT EXISTS florida_closest_mmsi_timestamps_geom_idx
ON public.florida_closest_mmsi_timestamps
USING GIST (geom);

CREATE INDEX IF NOT EXISTS florida_closest_mmsi_timestamps_mmsi_idx
ON public.florida_closest_mmsi_timestamps ("MMSI");

CREATE INDEX IF NOT EXISTS florida_closest_mmsi_timestamps_api_id_idx
ON public.florida_closest_mmsi_timestamps (api_id);

CREATE INDEX IF NOT EXISTS florida_closest_mmsi_timestamps_time_relation_idx
ON public.florida_closest_mmsi_timestamps (time_relation);

ANALYZE public.florida_closest_mmsi_timestamps;
