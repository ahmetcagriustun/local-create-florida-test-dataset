ALTER TABLE public.florida_sentinel2_metadata
DROP COLUMN IF EXISTS project_area_overlap_m2;

ALTER TABLE public.florida_sentinel2_metadata
DROP COLUMN IF EXISTS approx_cloud_free_overlap_m2;

ALTER TABLE public.florida_sentinel2_metadata
DROP COLUMN IF EXISTS water_area_m2;

ALTER TABLE public.florida_sentinel2_metadata
DROP COLUMN IF EXISTS approx_cloud_free_water_area_m2;

ALTER TABLE public.florida_sentinel2_metadata
ADD COLUMN IF NOT EXISTS water_area DOUBLE PRECISION;

WITH project_water_area AS (
    SELECT ST_Union(geom) AS geom
    FROM public.florida_project_area
),
intersection_areas AS (
    SELECT
        sm.product_id,
        ST_Area(
            ST_Intersection(
                ST_Transform(sm.geom, 3857),
                pwa.geom
            )
        ) AS total_water_area
    FROM public.florida_sentinel2_metadata sm
    CROSS JOIN project_water_area pwa
    WHERE ST_Intersects(ST_Transform(sm.geom, 3857), pwa.geom)
)
UPDATE public.florida_sentinel2_metadata sm
SET water_area = ia.total_water_area
FROM intersection_areas ia
WHERE sm.product_id = ia.product_id;

UPDATE public.florida_sentinel2_metadata
SET water_area = 0
WHERE water_area IS NULL;

ANALYZE public.florida_sentinel2_metadata;
