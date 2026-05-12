ALTER TABLE public.sentinel_download_index_geom_florida
ADD COLUMN IF NOT EXISTS api_id TEXT;

UPDATE public.sentinel_download_index_geom_florida
SET api_id = REGEXP_REPLACE(
    LEFT(file_name, LENGTH(file_name) - 4),
    '\.SAFE$',
    ''
)
WHERE file_name IS NOT NULL;

ALTER TABLE public.sentinel_download_index_geom_florida
ADD COLUMN IF NOT EXISTS sensing_time_without_tz TIMESTAMP WITHOUT TIME ZONE;

UPDATE public.sentinel_download_index_geom_florida
SET sensing_time_without_tz = timezone('UTC', sensing_time)
WHERE sensing_time IS NOT NULL
  AND sensing_time_without_tz IS NULL;

ALTER TABLE public.sentinel_download_index_geom_florida
ADD COLUMN IF NOT EXISTS geom_4326 geometry(Geometry, 4326);

UPDATE public.sentinel_download_index_geom_florida
SET geom_4326 = CASE
    WHEN ST_SRID(geom) = 4326 THEN geom
    ELSE ST_Transform(geom, 4326)
END
WHERE geom IS NOT NULL
  AND geom_4326 IS NULL;

CREATE INDEX IF NOT EXISTS idx_sentinel_florida_geom4326
ON public.sentinel_download_index_geom_florida
USING GIST (geom_4326);

CREATE INDEX IF NOT EXISTS idx_sentinel_florida_time
ON public.sentinel_download_index_geom_florida (sensing_time_without_tz);

CREATE INDEX IF NOT EXISTS idx_sentinel_florida_api_id
ON public.sentinel_download_index_geom_florida (api_id);

CREATE INDEX IF NOT EXISTS idx_ship_raw_data_florida_geom
ON public.ship_raw_data_florida
USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_ship_raw_data_florida_mmsi
ON public.ship_raw_data_florida ("MMSI");

CREATE INDEX IF NOT EXISTS idx_ship_raw_data_florida_timestamp
ON public.ship_raw_data_florida ("# Timestamp");

ANALYZE public.sentinel_download_index_geom_florida;
ANALYZE public.ship_raw_data_florida;
