DROP TABLE IF EXISTS public.florida_sentinel2_metadata_selected;

CREATE TABLE public.florida_sentinel2_metadata_selected AS
SELECT *
FROM public.florida_sentinel2_metadata
WHERE cloud_cover < 5
  AND water_area > 10000000
ORDER BY sensing_start;

CREATE INDEX IF NOT EXISTS florida_sentinel2_metadata_selected_geom_idx
ON public.florida_sentinel2_metadata_selected
USING GIST (geom);

CREATE INDEX IF NOT EXISTS florida_sentinel2_metadata_selected_sensing_time_idx
ON public.florida_sentinel2_metadata_selected (sensing_start);

ANALYZE public.florida_sentinel2_metadata_selected;
