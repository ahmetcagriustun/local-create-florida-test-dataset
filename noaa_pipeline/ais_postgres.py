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


def _get_target_dates(conn, source_date_table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT TO_CHAR(DATE(sensing_time), 'YYYY-MM-DD')
            FROM {source_date_table}
            ORDER BY 1
            """
        )
        return [row[0] for row in cur.fetchall()]


def _transform_chunk(chunk: pd.DataFrame, bbox: dict) -> pd.DataFrame:
    min_lon = float(bbox["min_lon"])
    min_lat = float(bbox["min_lat"])
    max_lon = float(bbox["max_lon"])
    max_lat = float(bbox["max_lat"])

    df = chunk.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    bbox_mask = (
        df["longitude"].between(min_lon, max_lon, inclusive="both")
        & df["latitude"].between(min_lat, max_lat, inclusive="both")
    )
    df = df.loc[bbox_mask].copy()
    if df.empty:
        return df

    timestamps = pd.to_datetime(df["base_date_time"], errors="coerce", utc=True)
    df = pd.DataFrame(
        {
            "# Timestamp": timestamps.dt.strftime("%Y-%m-%d %H:%M:%S"),
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

    df = df.dropna(subset=["# Timestamp", "MMSI", "Latitude", "Longitude"])
    return df


def _copy_dataframe(cur, table_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return

    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=True)
    buffer.seek(0)

    copy_sql = f"""
        COPY {table_name} (
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
    """
    cur.copy_expert(copy_sql, buffer)


def _ensure_geom_and_indexes(cur, table_name: str) -> None:
    cur.execute(
        f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS id BIGSERIAL;
        """
    )
    cur.execute(
        f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS geom geometry(POINT, 4326);
        """
    )
    cur.execute(
        f"""
        UPDATE {table_name}
        SET geom = ST_SetSRID(ST_MakePoint("Longitude", "Latitude"), 4326)
        WHERE geom IS NULL
          AND "Longitude" IS NOT NULL
          AND "Latitude" IS NOT NULL;
        """
    )
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_ship_raw_data_florida_timestamp ON {table_name} ("# Timestamp");')
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_ship_raw_data_florida_mmsi ON {table_name} ("MMSI");')
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_ship_raw_data_florida_geom ON {table_name} USING GIST (geom);')


def import_ship_raw_data_florida(config: dict, truncate: bool = False) -> int:
    pg_cfg = config["postgres"]
    ais_pg_cfg = config["ais_postgres"]
    raw_dir = Path(config["paths"]["raw_dir"])
    bbox = config["study_area"]["bbox"]
    table_name = ais_pg_cfg["target_table"]
    chunksize = int(ais_pg_cfg.get("chunksize", 200000))
    source_date_table = ais_pg_cfg["source_date_table"]

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(table_name=table_name))
            if truncate:
                cur.execute(f"TRUNCATE TABLE {table_name};")
            conn.commit()

            dates = _get_target_dates(conn, source_date_table)
            total_rows = 0
            for date_str in dates:
                raw_path = raw_dir / f"ais-{date_str}.csv.zst"
                if not raw_path.exists():
                    raise FileNotFoundError(raw_path)

                print(f"importing={raw_path.name}")
                for chunk in pd.read_csv(
                    raw_path,
                    usecols=RAW_USECOLS,
                    chunksize=chunksize,
                    compression="zstd",
                ):
                    transformed = _transform_chunk(chunk, bbox)
                    if transformed.empty:
                        continue
                    _copy_dataframe(cur, table_name, transformed)
                    total_rows += len(transformed)
                conn.commit()

            _ensure_geom_and_indexes(cur, table_name)
            conn.commit()

    print(f"ship_raw_data_rows={total_rows}")
    print(f"ship_raw_data_table={table_name}")
    return total_rows
