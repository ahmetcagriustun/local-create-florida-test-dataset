DROP TABLE IF EXISTS public.florida_project_area_candidates;

CREATE TABLE public.florida_project_area_candidates (
    id INTEGER PRIMARY KEY,
    area_key TEXT NOT NULL UNIQUE,
    area_name TEXT NOT NULL,
    area_role TEXT NOT NULL,
    notes TEXT,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    geom geometry(Polygon, 4326) NOT NULL
);

INSERT INTO public.florida_project_area_candidates (
    id,
    area_key,
    area_name,
    area_role,
    notes,
    min_lon,
    min_lat,
    max_lon,
    max_lat,
    geom
)
VALUES
(
    1,
    'south_florida_original',
    'South Florida Original Project Area',
    'original_project_area',
    'Original Florida project area used for the first NOAA-Sentinel-2 external test set.',
    -82.0,
    24.2,
    -79.4,
    27.2,
    ST_MakeEnvelope(-82.0, 24.2, -79.4, 27.2, 4326)
),
(
    2,
    'fishing_enriched_west_keys',
    'Fishing-Enriched West Keys / Dry Tortugas Shelf',
    'new_candidate_area',
    'Recommended AOI to increase Fishing samples with relatively lower co-occurring pressure from Pleasure and Cargo/Tanker.',
    -83.0,
    24.5,
    -82.0,
    25.5,
    ST_MakeEnvelope(-83.0, 24.5, -82.0, 25.5, 4326)
),
(
    3,
    'balanced_passenger_tampa_side',
    'Balanced Passenger Candidate Area',
    'new_candidate_area',
    'Recommended AOI to improve Passenger counts while keeping a more balanced mix than the Miami high-volume corridor.',
    -82.5,
    27.5,
    -82.0,
    28.0,
    ST_MakeEnvelope(-82.5, 27.5, -82.0, 28.0, 4326)
);

CREATE INDEX florida_project_area_candidates_geom_gix
ON public.florida_project_area_candidates
USING GIST (geom);
