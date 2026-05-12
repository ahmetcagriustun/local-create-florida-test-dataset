WITH selected_scenes AS (
    SELECT
        product_id,
        sensing_start,
        DATE(timezone('UTC', sensing_start)) AS sensing_date,
        cloud_cover,
        water_area
    FROM public.florida_sentinel2_metadata_selected
),
ais_daily AS (
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
        ss.*,
        COALESCE(ad.total_rows, 0) AS total_rows,
        COALESCE(ad.distinct_mmsi, 0) AS distinct_mmsi,
        COALESCE(ad.passenger_rows, 0) AS passenger_rows,
        COALESCE(ad.fishing_rows, 0) AS fishing_rows,
        COALESCE(ad.passenger_rows, 0) + COALESCE(ad.fishing_rows, 0) AS target_rows
    FROM selected_scenes ss
    LEFT JOIN ais_daily ad
      ON ss.sensing_date = ad.ais_date
),
thresholds AS (
    SELECT
        percentile_disc(0.50) WITHIN GROUP (ORDER BY target_rows) AS p50_target_rows,
        percentile_disc(0.75) WITHIN GROUP (ORDER BY target_rows) AS p75_target_rows,
        percentile_disc(0.90) WITHIN GROUP (ORDER BY target_rows) AS p90_target_rows,
        percentile_disc(0.50) WITHIN GROUP (ORDER BY water_area) AS p50_water_area,
        percentile_disc(0.75) WITHIN GROUP (ORDER BY water_area) AS p75_water_area
    FROM scene_daily
)
SELECT
    t.*,
    (SELECT COUNT(*) FROM scene_daily WHERE target_rows >= t.p50_target_rows) AS scenes_target_ge_p50,
    (SELECT COUNT(*) FROM scene_daily WHERE target_rows >= t.p75_target_rows) AS scenes_target_ge_p75,
    (SELECT COUNT(*) FROM scene_daily WHERE target_rows >= t.p90_target_rows) AS scenes_target_ge_p90,
    (SELECT COUNT(*) FROM scene_daily WHERE target_rows >= t.p75_target_rows AND water_area >= t.p50_water_area) AS scenes_target_ge_p75_water_ge_p50,
    (SELECT COUNT(*) FROM scene_daily WHERE target_rows >= t.p75_target_rows AND water_area >= t.p75_water_area) AS scenes_target_ge_p75_water_ge_p75
FROM thresholds t;
