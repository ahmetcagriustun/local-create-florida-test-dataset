ALTER TABLE public.florida_sentinel2_download_index_geom
ADD COLUMN IF NOT EXISTS api_id TEXT;

UPDATE public.florida_sentinel2_download_index_geom
SET api_id = REGEXP_REPLACE(
    LEFT(file_name, LENGTH(file_name) - 4),
    '\.SAFE$',
    ''
)
WHERE file_name IS NOT NULL;

ALTER TABLE public.florida_sentinel2_download_index_geom
ADD COLUMN IF NOT EXISTS sensing_time_without_tz TIMESTAMP WITHOUT TIME ZONE;

UPDATE public.florida_sentinel2_download_index_geom
SET sensing_time_without_tz = timezone('UTC', sensing_time)
WHERE sensing_time IS NOT NULL
  AND sensing_time_without_tz IS NULL;

ALTER TABLE public.florida_sentinel2_download_index_geom
ADD COLUMN IF NOT EXISTS geom_4326 geometry(Geometry, 4326);

UPDATE public.florida_sentinel2_download_index_geom
SET geom_4326 = CASE
    WHEN ST_SRID(geom) = 4326 THEN geom
    ELSE ST_Transform(geom, 4326)
END
WHERE geom IS NOT NULL
  AND geom_4326 IS NULL;

CREATE INDEX IF NOT EXISTS florida_sentinel2_download_index_geom_geom4326_idx
ON public.florida_sentinel2_download_index_geom
USING GIST (geom_4326);

CREATE INDEX IF NOT EXISTS florida_sentinel2_download_index_geom_time_idx
ON public.florida_sentinel2_download_index_geom (sensing_time_without_tz);

CREATE INDEX IF NOT EXISTS florida_sentinel2_download_index_geom_api_id_idx
ON public.florida_sentinel2_download_index_geom (api_id);

CREATE INDEX IF NOT EXISTS florida_ship_raw_data_geom_idx
ON public.florida_ship_raw_data
USING GIST (geom);

CREATE INDEX IF NOT EXISTS florida_ship_raw_data_mmsi_idx
ON public.florida_ship_raw_data ("MMSI");

CREATE INDEX IF NOT EXISTS florida_ship_raw_data_timestamp_idx
ON public.florida_ship_raw_data ("# Timestamp");

ANALYZE public.florida_sentinel2_download_index_geom;
ANALYZE public.florida_ship_raw_data;
