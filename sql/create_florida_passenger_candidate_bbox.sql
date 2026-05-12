DROP TABLE IF EXISTS public.florida_passenger_candidate_bbox;

CREATE TABLE public.florida_passenger_candidate_bbox (
    id INTEGER PRIMARY KEY,
    area_key TEXT NOT NULL UNIQUE,
    area_name TEXT NOT NULL,
    notes TEXT,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    geom geometry(Polygon, 4326) NOT NULL
);

INSERT INTO public.florida_passenger_candidate_bbox (
    id,
    area_key,
    area_name,
    notes,
    min_lon,
    min_lat,
    max_lon,
    max_lat,
    geom
)
VALUES (
    1,
    'passenger_candidate_bbox_raw',
    'Passenger Candidate Raw Bounding Box',
    'User-defined broad passenger candidate area before intersecting with water polygons.',
    -84.0,
    24.0,
    -79.0,
    28.0,
    ST_MakeEnvelope(-84.0, 24.0, -79.0, 28.0, 4326)
);

CREATE INDEX florida_passenger_candidate_bbox_geom_gix
ON public.florida_passenger_candidate_bbox
USING GIST (geom);
