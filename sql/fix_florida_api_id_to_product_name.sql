-- Adapted from the old repo logic in:
-- ais-sentinel2-shiptype-classification-main/sql/create-sentinel_download_index_geom.sql
--
-- Old logic used the downloaded Sentinel-2 SAFE file name as the working product id.
-- For the Florida pipeline we keep the same idea, but strip both ".zip" and ".SAFE"
-- so api_id matches values like:
-- S2A_MSIL2A_20220226T104011_N0400_R008_T32VPK_20220226T135412

ALTER TABLE public.sentinel_download_index_geom_florida
ADD COLUMN IF NOT EXISTS api_id TEXT;

UPDATE public.sentinel_download_index_geom_florida
SET api_id = REGEXP_REPLACE(
    LEFT(file_name, LENGTH(file_name) - 4),
    '\.SAFE$',
    ''
)
WHERE file_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sentinel_florida_api_id
ON public.sentinel_download_index_geom_florida (api_id);

ANALYZE public.sentinel_download_index_geom_florida;
