from __future__ import annotations

from pathlib import Path

import psycopg2


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    source_mmsi TEXT,
    timestamp_utc TIMESTAMPTZ,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    sog DOUBLE PRECISION,
    cog DOUBLE PRECISION,
    heading DOUBLE PRECISION,
    vessel_name TEXT,
    imo TEXT,
    call_sign TEXT,
    vessel_type_code INTEGER,
    status_code INTEGER,
    length_m DOUBLE PRECISION,
    width_m DOUBLE PRECISION,
    draft_m DOUBLE PRECISION,
    cargo_code INTEGER,
    transceiver_class TEXT,
    target_class_6 TEXT
);
"""


def _connect(pg_cfg: dict):
    return psycopg2.connect(
        host=pg_cfg["host"],
        port=pg_cfg.get("port", 5432),
        dbname=pg_cfg["dbname"],
        user=pg_cfg["user"],
        password=pg_cfg["password"],
    )


def import_csv_to_postgres(config: dict, csv_path: str | Path | None = None, truncate: bool = False) -> None:
    pg_cfg = config["postgres"]
    schema = pg_cfg.get("schema", "public")
    table = pg_cfg["table"]

    if csv_path is None:
        csv_path = Path(config["paths"]["merged_dir"]) / "south_florida_2023h1_merged.csv.gz"
    else:
        csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    copy_sql = f"""
    COPY {schema}.{table} (
        source_mmsi,
        timestamp_utc,
        lat,
        lon,
        sog,
        cog,
        heading,
        vessel_name,
        imo,
        call_sign,
        vessel_type_code,
        status_code,
        length_m,
        width_m,
        draft_m,
        cargo_code,
        transceiver_class,
        target_class_6
    )
    FROM STDIN WITH (FORMAT csv, HEADER true);
    """

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(schema=schema, table=table))
            if truncate:
                cur.execute(f"TRUNCATE TABLE {schema}.{table};")
            conn.commit()

            open_fn = open
            if csv_path.suffix == ".gz":
                import gzip

                open_fn = gzip.open

            with open_fn(csv_path, "rt", encoding="utf-8", newline="") as handle:
                cur.copy_expert(copy_sql, handle)
            conn.commit()

            cur.execute(
                f"""
                ALTER TABLE {schema}.{table}
                ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);
                """
            )
            cur.execute(
                f"""
                UPDATE {schema}.{table}
                SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                WHERE geom IS NULL AND lon IS NOT NULL AND lat IS NOT NULL;
                """
            )
            conn.commit()

    print(f"imported={csv_path} table={schema}.{table}")
