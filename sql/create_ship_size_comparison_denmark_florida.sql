DROP TABLE IF EXISTS public.ship_size_comparison_closest_timestamp_denmark_florida;

CREATE TABLE public.ship_size_comparison_closest_timestamp_denmark_florida AS
WITH denmark_labeled AS (
    SELECT
        CASE
            WHEN cmt."Ship type" IN ('Cargo', 'Tanker', 'Fishing', 'Passenger', 'Sailing', 'Pleasure')
                THEN cmt."Ship type"
            ELSE NULL
        END AS ship_class,
        cmt."Length" AS length_m,
        cmt."Width" AS width_m
    FROM public.closest_mmsi_timestamps cmt
),
florida_coded AS (
    SELECT
        CASE
            WHEN cmtf."Ship type" ~ '^[0-9]+(\.[0-9]+)?$' THEN FLOOR((cmtf."Ship type")::numeric)::int
            ELSE NULL
        END AS ship_type_code_int,
        cmtf."Length" AS length_m,
        cmtf."Width" AS width_m
    FROM public.closest_mmsi_timestamps_florida cmtf
),
florida_labeled AS (
    SELECT
        CASE
            WHEN ship_type_code_int = 30 THEN 'Fishing'
            WHEN ship_type_code_int = 36 THEN 'Sailing'
            WHEN ship_type_code_int = 37 THEN 'Pleasure'
            WHEN ship_type_code_int BETWEEN 60 AND 69 THEN 'Passenger'
            WHEN ship_type_code_int BETWEEN 70 AND 79 THEN 'Cargo'
            WHEN ship_type_code_int BETWEEN 80 AND 89 THEN 'Tanker'
            ELSE NULL
        END AS ship_class,
        length_m,
        width_m
    FROM florida_coded
),
denmark_stats AS (
    SELECT
        ship_class,
        COUNT(*) AS denmark_total_rows,
        COUNT(length_m) AS denmark_length_nonnull_count,
        ROUND(AVG(length_m)::numeric, 2) AS denmark_length_mean_m,
        ROUND(MIN(length_m)::numeric, 2) AS denmark_length_min_m,
        ROUND(MAX(length_m)::numeric, 2) AS denmark_length_max_m,
        COUNT(width_m) AS denmark_width_nonnull_count,
        ROUND(AVG(width_m)::numeric, 2) AS denmark_width_mean_m,
        ROUND(MIN(width_m)::numeric, 2) AS denmark_width_min_m,
        ROUND(MAX(width_m)::numeric, 2) AS denmark_width_max_m
    FROM denmark_labeled
    WHERE ship_class IS NOT NULL
    GROUP BY ship_class
),
florida_stats AS (
    SELECT
        ship_class,
        COUNT(*) AS florida_total_rows,
        COUNT(length_m) AS florida_length_nonnull_count,
        ROUND(AVG(length_m)::numeric, 2) AS florida_length_mean_m,
        ROUND(MIN(length_m)::numeric, 2) AS florida_length_min_m,
        ROUND(MAX(length_m)::numeric, 2) AS florida_length_max_m,
        COUNT(width_m) AS florida_width_nonnull_count,
        ROUND(AVG(width_m)::numeric, 2) AS florida_width_mean_m,
        ROUND(MIN(width_m)::numeric, 2) AS florida_width_min_m,
        ROUND(MAX(width_m)::numeric, 2) AS florida_width_max_m
    FROM florida_labeled
    WHERE ship_class IS NOT NULL
    GROUP BY ship_class
)
SELECT
    COALESCE(d.ship_class, f.ship_class) AS ship_class,
    d.denmark_total_rows,
    d.denmark_length_nonnull_count,
    d.denmark_length_mean_m,
    d.denmark_length_min_m,
    d.denmark_length_max_m,
    d.denmark_width_nonnull_count,
    d.denmark_width_mean_m,
    d.denmark_width_min_m,
    d.denmark_width_max_m,
    f.florida_total_rows,
    f.florida_length_nonnull_count,
    f.florida_length_mean_m,
    f.florida_length_min_m,
    f.florida_length_max_m,
    f.florida_width_nonnull_count,
    f.florida_width_mean_m,
    f.florida_width_min_m,
    f.florida_width_max_m
FROM denmark_stats d
FULL OUTER JOIN florida_stats f
    ON d.ship_class = f.ship_class
ORDER BY CASE COALESCE(d.ship_class, f.ship_class)
    WHEN 'Cargo' THEN 1
    WHEN 'Tanker' THEN 2
    WHEN 'Fishing' THEN 3
    WHEN 'Passenger' THEN 4
    WHEN 'Sailing' THEN 5
    WHEN 'Pleasure' THEN 6
    ELSE 999
END;
