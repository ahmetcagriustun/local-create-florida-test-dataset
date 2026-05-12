DROP TABLE IF EXISTS public.florida_ship_predicted_positions_open_sea;

CREATE TABLE public.florida_ship_predicted_positions_open_sea AS
WITH coded AS (
    SELECT
        spp.*,
        CASE
            WHEN spp."Ship type" ~ '^[0-9]+(\.[0-9]+)?$' THEN FLOOR((spp."Ship type")::numeric)::int
            ELSE NULL
        END AS ship_type_code_int
    FROM public.florida_ship_predicted_positions spp
),
labeled AS (
    SELECT
        c.id,
        c."MMSI",
        c."Ship type" AS "Ship type code raw",
        c.ship_type_code_int AS "Ship type code",
        CASE c.ship_type_code_int
            WHEN 10 THEN 'Reserved for Future Use'
            WHEN 30 THEN 'Fishing'
            WHEN 31 THEN 'Towing'
            WHEN 32 THEN 'Towing: Length > 200 m or Breadth > 25 m'
            WHEN 33 THEN 'Dredging or Underwater Operations'
            WHEN 34 THEN 'Diving Operations'
            WHEN 35 THEN 'Military Operations'
            WHEN 36 THEN 'Sailing'
            WHEN 37 THEN 'Pleasure Craft'
            WHEN 40 THEN 'High-Speed Craft'
            WHEN 51 THEN 'Search and Rescue'
            WHEN 52 THEN 'Tug'
            WHEN 55 THEN 'Law Enforcement'
            WHEN 56 THEN 'Spare - Local Vessel'
            WHEN 60 THEN 'Passenger'
            WHEN 61 THEN 'Passenger, Hazardous Category A'
            WHEN 62 THEN 'Passenger, Hazardous Category B'
            WHEN 63 THEN 'Passenger, Hazardous Category C'
            WHEN 64 THEN 'Passenger, Hazardous Category D'
            WHEN 65 THEN 'Passenger, Reserved'
            WHEN 66 THEN 'Passenger, Reserved'
            WHEN 67 THEN 'Passenger, Reserved'
            WHEN 68 THEN 'Passenger, Reserved'
            WHEN 69 THEN 'Passenger, No Additional Information'
            WHEN 70 THEN 'Cargo'
            WHEN 71 THEN 'Cargo, Hazardous Category A'
            WHEN 72 THEN 'Cargo, Hazardous Category B'
            WHEN 73 THEN 'Cargo, Hazardous Category C'
            WHEN 74 THEN 'Cargo, Hazardous Category D'
            WHEN 75 THEN 'Cargo, Reserved'
            WHEN 76 THEN 'Cargo, Reserved'
            WHEN 77 THEN 'Cargo, Reserved'
            WHEN 78 THEN 'Cargo, Reserved'
            WHEN 79 THEN 'Cargo, No Additional Information'
            WHEN 80 THEN 'Tanker'
            WHEN 81 THEN 'Tanker, Hazardous Category A'
            WHEN 82 THEN 'Tanker, Hazardous Category B'
            WHEN 83 THEN 'Tanker, Hazardous Category C'
            WHEN 84 THEN 'Tanker, Hazardous Category D'
            WHEN 85 THEN 'Tanker, Reserved'
            WHEN 86 THEN 'Tanker, Reserved'
            WHEN 87 THEN 'Tanker, Reserved'
            WHEN 88 THEN 'Tanker, Reserved'
            WHEN 89 THEN 'Tanker, No Additional Information'
            WHEN 90 THEN 'Other'
            WHEN 99 THEN 'Other, No Additional Information'
            ELSE 'Unknown'
        END AS "Ship type",
        CASE
            WHEN c.ship_type_code_int = 30 THEN 'Fishing'
            WHEN c.ship_type_code_int = 36 THEN 'Sailing'
            WHEN c.ship_type_code_int = 37 THEN 'Pleasure'
            WHEN c.ship_type_code_int BETWEEN 60 AND 69 THEN 'Passenger'
            WHEN c.ship_type_code_int BETWEEN 70 AND 79 THEN 'Cargo'
            WHEN c.ship_type_code_int BETWEEN 80 AND 89 THEN 'Tanker'
            ELSE NULL
        END AS "Target ship type",
        c."Length",
        c.api_id,
        c.sensing_time_without_tz,
        c.geom
    FROM coded c
    WHERE EXISTS (
        SELECT 1
        FROM public.florida_project_area pa
        WHERE ST_Intersects(
            c.geom,
            ST_Transform(pa.geom, 4326)
        )
    )
)
SELECT *
FROM labeled;

CREATE INDEX IF NOT EXISTS florida_ship_predicted_positions_open_sea_geom_idx
ON public.florida_ship_predicted_positions_open_sea
USING GIST (geom);

CREATE INDEX IF NOT EXISTS florida_ship_predicted_positions_open_sea_mmsi_idx
ON public.florida_ship_predicted_positions_open_sea ("MMSI");

CREATE INDEX IF NOT EXISTS florida_ship_predicted_positions_open_sea_api_id_idx
ON public.florida_ship_predicted_positions_open_sea (api_id);

CREATE INDEX IF NOT EXISTS florida_ship_predicted_positions_open_sea_sensing_time_idx
ON public.florida_ship_predicted_positions_open_sea (sensing_time_without_tz);

CREATE INDEX IF NOT EXISTS florida_ship_predicted_positions_open_sea_target_type_idx
ON public.florida_ship_predicted_positions_open_sea ("Target ship type");

ANALYZE public.florida_ship_predicted_positions_open_sea;
