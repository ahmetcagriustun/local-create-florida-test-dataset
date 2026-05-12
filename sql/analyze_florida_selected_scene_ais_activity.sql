WITH selected_days AS (
    SELECT DISTINCT DATE(timezone('UTC', sensing_start)) AS sensing_date
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
)
SELECT
    sd.sensing_date,
    COALESCE(ad.total_rows, 0) AS total_rows,
    COALESCE(ad.distinct_mmsi, 0) AS distinct_mmsi,
    COALESCE(ad.passenger_rows, 0) AS passenger_rows,
    COALESCE(ad.fishing_rows, 0) AS fishing_rows,
    COALESCE(ad.passenger_rows, 0) + COALESCE(ad.fishing_rows, 0) AS target_rows
FROM selected_days sd
LEFT JOIN ais_daily ad
  ON sd.sensing_date = ad.ais_date
ORDER BY target_rows DESC, total_rows DESC, sd.sensing_date;
