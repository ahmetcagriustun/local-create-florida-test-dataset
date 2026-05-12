from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import psycopg2


RAW_USECOLS = [
    "mmsi",
    "base_date_time",
    "latitude",
    "longitude",
    "sog",
    "cog",
    "heading",
    "vessel_name",
    "imo",
    "call_sign",
    "vessel_type",
    "status",
    "length",
    "width",
    "draft",
    "cargo",
    "transceiver",
]


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    "# Timestamp" TIMESTAMP,
    "Type of mobile" VARCHAR(255),
    "MMSI" BIGINT,
    "Latitude" DOUBLE PRECISION,
    "Longitude" DOUBLE PRECISION,
    "Navigational status" VARCHAR(255),
    "ROT" DOUBLE PRECISION,
    "SOG" DOUBLE PRECISION,
    "COG" DOUBLE PRECISION,
    "Heading" DOUBLE PRECISION,
    "IMO" VARCHAR(255),
    "Callsign" VARCHAR(255),
    "Name" VARCHAR(255),
    "Ship type" VARCHAR(255),
    "Cargo type" VARCHAR(255),
    "Width" DOUBLE PRECISION,
    "Length" DOUBLE PRECISION,
    "Type of position fixing device" VARCHAR(255),
    "Draught" DOUBLE PRECISION,
    "Destination" VARCHAR(255),
    "ETA" VARCHAR(255),
    "Data source type" VARCHAR(255),
    "A" DOUBLE PRECISION,
    "B" DOUBLE PRECISION,
    "C" DOUBLE PRECISION,
    "D" DOUBLE PRECISION,
    id BIGSERIAL,
    geom geometry(Point, 4326)
);
"""


TEMP_STAGE_SQL = """
CREATE TEMP TABLE temp_ship_raw_stage (
    "# Timestamp" TIMESTAMP,
    "Type of mobile" VARCHAR(255),
    "MMSI" BIGINT,
    "Latitude" DOUBLE PRECISION,
    "Longitude" DOUBLE PRECISION,
    "Navigational status" VARCHAR(255),
    "ROT" DOUBLE PRECISION,
    "SOG" DOUBLE PRECISION,
    "COG" DOUBLE PRECISION,
    "Heading" DOUBLE PRECISION,
    "IMO" VARCHAR(255),
    "Callsign" VARCHAR(255),
    "Name" VARCHAR(255),
    "Ship type" VARCHAR(255),
    "Cargo type" VARCHAR(255),
    "Width" DOUBLE PRECISION,
    "Length" DOUBLE PRECISION,
    "Type of position fixing device" VARCHAR(255),
    "Draught" DOUBLE PRECISION,
    "Destination" VARCHAR(255),
    "ETA" VARCHAR(255),
    "Data source type" VARCHAR(255),
    "A" DOUBLE PRECISION,
    "B" DOUBLE PRECISION,
    "C" DOUBLE PRECISION,
    "D" DOUBLE PRECISION
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


def _iter_target_files(raw_dir: Path, start_date: str, end_date: str) -> list[Path]:
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    files: list[Path] = []
    for path in sorted(raw_dir.glob("ais-*.csv.zst")):
        try:
            date_part = path.stem.replace("ais-", "").replace(".csv", "")
            file_date = pd.Timestamp(date_part).date()
        except Exception:
            continue
        if start <= file_date <= end:
            files.append(path)
    return files


def _get_project_area_bbox_and_geom(cur, area_table: str) -> dict:
    cur.execute(
        f"""
        SELECT
            MIN(min_lon) AS min_lon,
            MIN(min_lat) AS min_lat,
            MAX(max_lon) AS max_lon,
            MAX(max_lat) AS max_lat,
            ST_AsEWKT(ST_Transform(ST_Union(geom), 4326)) AS geom_4326_wkt
        FROM {area_table};
        """
    )
    row = cur.fetchone()
    if row is None or row[0] is None or row[4] is None:
        raise RuntimeError(f"Area table is empty or invalid: {area_table}")
    return {
        "min_lon": float(row[0]),
        "min_lat": float(row[1]),
        "max_lon": float(row[2]),
        "max_lat": float(row[3]),
        "geom_4326_wkt": str(row[4]),
    }


def _transform_chunk_bbox_only(chunk: pd.DataFrame, bbox: dict) -> pd.DataFrame:
    df = chunk.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    df = df.loc[
        df["longitude"].between(float(bbox["min_lon"]), float(bbox["max_lon"]), inclusive="both")
        & df["latitude"].between(float(bbox["min_lat"]), float(bbox["max_lat"]), inclusive="both")
    ].copy()
    if df.empty:
        return df

    timestamps = pd.to_datetime(df["base_date_time"], errors="coerce")
    out = pd.DataFrame(
        {
            "# Timestamp": timestamps,
            "Type of mobile": df["transceiver"].astype("string"),
            "MMSI": pd.to_numeric(df["mmsi"], errors="coerce").astype("Int64"),
            "Latitude": df["latitude"],
            "Longitude": df["longitude"],
            "Navigational status": df["status"].astype("string"),
            "ROT": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "SOG": pd.to_numeric(df["sog"], errors="coerce"),
            "COG": pd.to_numeric(df["cog"], errors="coerce"),
            "Heading": pd.to_numeric(df["heading"], errors="coerce"),
            "IMO": df["imo"].astype("string"),
            "Callsign": df["call_sign"].astype("string"),
            "Name": df["vessel_name"].astype("string"),
            "Ship type": df["vessel_type"].astype("string"),
            "Cargo type": df["cargo"].astype("string"),
            "Width": pd.to_numeric(df["width"], errors="coerce"),
            "Length": pd.to_numeric(df["length"], errors="coerce"),
            "Type of position fixing device": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "Draught": pd.to_numeric(df["draft"], errors="coerce"),
            "Destination": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "ETA": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "Data source type": pd.Series(["NOAA_AccessAIS"] * len(df), index=df.index, dtype="object"),
            "A": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "B": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "C": pd.Series([None] * len(df), index=df.index, dtype="object"),
            "D": pd.Series([None] * len(df), index=df.index, dtype="object"),
        }
    )
    out = out.dropna(subset=["# Timestamp", "MMSI", "Latitude", "Longitude"])
    return out


def _copy_dataframe_to_stage(cur, df: pd.DataFrame) -> None:
    if df.empty:
        return
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=True)
    buffer.seek(0)
    cur.copy_expert(
        """
        COPY temp_ship_raw_stage (
            "# Timestamp",
            "Type of mobile",
            "MMSI",
            "Latitude",
            "Longitude",
            "Navigational status",
            "ROT",
            "SOG",
            "COG",
            "Heading",
            "IMO",
            "Callsign",
            "Name",
            "Ship type",
            "Cargo type",
            "Width",
            "Length",
            "Type of position fixing device",
            "Draught",
            "Destination",
            "ETA",
            "Data source type",
            "A",
            "B",
            "C",
            "D"
        )
        FROM STDIN WITH (FORMAT csv, HEADER true);
        """,
        buffer,
    )


def _insert_stage_into_target(cur, target_table: str, area_geom_4326_wkt: str) -> int:
    cur.execute(
        f"""
        WITH area AS (
            SELECT ST_GeomFromEWKT(%s)::geometry(Geometry, 4326) AS geom
        ),
        inserted AS (
            INSERT INTO {target_table} (
                "# Timestamp",
                "Type of mobile",
                "MMSI",
                "Latitude",
                "Longitude",
                "Navigational status",
                "ROT",
                "SOG",
                "COG",
                "Heading",
                "IMO",
                "Callsign",
                "Name",
                "Ship type",
                "Cargo type",
                "Width",
                "Length",
                "Type of position fixing device",
                "Draught",
                "Destination",
                "ETA",
                "Data source type",
                "A",
                "B",
                "C",
                "D",
                geom
            )
            SELECT
                s."# Timestamp",
                s."Type of mobile",
                s."MMSI",
                s."Latitude",
                s."Longitude",
                s."Navigational status",
                s."ROT",
                s."SOG",
                s."COG",
                s."Heading",
                s."IMO",
                s."Callsign",
                s."Name",
                s."Ship type",
                s."Cargo type",
                s."Width",
                s."Length",
                s."Type of position fixing device",
                s."Draught",
                s."Destination",
                s."ETA",
                s."Data source type",
                s."A",
                s."B",
                s."C",
                s."D",
                ST_SetSRID(ST_MakePoint(s."Longitude", s."Latitude"), 4326) AS geom
            FROM temp_ship_raw_stage s
            CROSS JOIN area a
            WHERE ST_Intersects(
                a.geom,
                ST_SetSRID(ST_MakePoint(s."Longitude", s."Latitude"), 4326)
            )
            RETURNING 1
        )
        SELECT COUNT(*) FROM inserted;
        """,
        (area_geom_4326_wkt,),
    )
    inserted_count = int(cur.fetchone()[0])
    return inserted_count


def _ensure_indexes(cur, target_table: str) -> None:
    safe_name = target_table.replace(".", "_")
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_name}_timestamp ON {target_table} ("# Timestamp");')
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_name}_mmsi ON {target_table} ("MMSI");')
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_name}_geom ON {target_table} USING GIST (geom);')


def import_ship_raw_data_for_project_area(
    config: dict,
    *,
    area_table: str,
    target_table: str,
    truncate: bool = False,
    chunksize: int | None = None,
) -> int:
    pg_cfg = config["postgres"]
    raw_dir = Path(config["paths"]["raw_dir"])
    start_date = str(config["study_area"]["start_date"])
    end_date = str(config["study_area"]["end_date"])
    chunk_size = int(chunksize or config.get("ais_postgres", {}).get("chunksize", 200000))

    files = _iter_target_files(raw_dir, start_date, end_date)
    if not files:
        raise FileNotFoundError(f"No NOAA raw files found in {raw_dir} for {start_date}..{end_date}")

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            bbox_and_geom = _get_project_area_bbox_and_geom(cur, area_table)
            cur.execute(CREATE_TABLE_SQL.format(table_name=target_table))
            if truncate:
                cur.execute(f"TRUNCATE TABLE {target_table};")
            cur.execute("DROP TABLE IF EXISTS temp_ship_raw_stage;")
            cur.execute(TEMP_STAGE_SQL)
            conn.commit()

            total_inserted = 0
            for raw_path in files:
                print(f"importing={raw_path.name}")
                for chunk in pd.read_csv(
                    raw_path,
                    usecols=RAW_USECOLS,
                    chunksize=chunk_size,
                    compression="zstd",
                    low_memory=False,
                ):
                    transformed = _transform_chunk_bbox_only(chunk, bbox_and_geom)
                    if transformed.empty:
                        continue
                    cur.execute("TRUNCATE TABLE temp_ship_raw_stage;")
                    _copy_dataframe_to_stage(cur, transformed)
                    total_inserted += _insert_stage_into_target(cur, target_table, bbox_and_geom["geom_4326_wkt"])
                conn.commit()

            _ensure_indexes(cur, target_table)
            conn.commit()

    print(f"ship_raw_data_rows={total_inserted}")
    print(f"ship_raw_data_table={target_table}")
    return total_inserted
