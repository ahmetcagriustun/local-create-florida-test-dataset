from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


def _connect(pg_cfg: dict):
    return psycopg2.connect(
        host=pg_cfg["host"],
        port=pg_cfg.get("port", 5432),
        dbname=pg_cfg["dbname"],
        user=pg_cfg["user"],
        password=pg_cfg["password"],
    )


def _safe_index_name(table_name: str, suffix: str) -> str:
    normalized = table_name.replace(".", "_").replace('"', "").replace("-", "_")
    return f"{normalized}_{suffix}"


def _extract_sensing_time(zip_path: Path) -> str | None:
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        xml_member = next((name for name in zip_ref.namelist() if "MTD_TL.xml" in name), None)
        if not xml_member:
            return None
        with zip_ref.open(xml_member) as handle:
            xml_content = handle.read()
    root = ET.fromstring(xml_content)
    sensing_time = root.find(".//SENSING_TIME")
    return sensing_time.text if sensing_time is not None else None


def build_local_download_index(config: dict, truncate: bool = False) -> int:
    pg_cfg = config["postgres"]
    s2_download_cfg = config["sentinel2_download"]
    s2_index_cfg = config["sentinel2_index"]

    zip_dir = Path(s2_download_cfg["output_dir"])
    table_name = s2_index_cfg["download_index_table"]

    zip_files = sorted(zip_dir.glob("*.zip"))
    if not zip_files:
        raise FileNotFoundError(f"No Sentinel-2 ZIP files found in {zip_dir}")

    rows = []
    for zip_path in zip_files:
        sensing_time = _extract_sensing_time(zip_path)
        rows.append((zip_path.name, sensing_time))

    sensing_index_name = _safe_index_name(table_name, "sensing_time_idx")

    ddl = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        file_name TEXT PRIMARY KEY,
        sensing_time TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS {sensing_index_name} ON {table_name}(sensing_time);
    """

    upsert_sql = f"""
    INSERT INTO {table_name} (file_name, sensing_time)
    VALUES %s
    ON CONFLICT (file_name) DO UPDATE SET
        sensing_time = EXCLUDED.sensing_time;
    """

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            if truncate:
                cur.execute(f"TRUNCATE TABLE {table_name};")
            execute_values(cur, upsert_sql, rows, page_size=100)
            conn.commit()

    print(f"sentinel2_download_index_rows={len(rows)}")
    print(f"sentinel2_download_index_table={table_name}")
    return len(rows)


def build_local_download_index_geom(config: dict, drop_existing: bool = True) -> None:
    pg_cfg = config["postgres"]
    s2_index_cfg = config["sentinel2_index"]

    download_index_table = s2_index_cfg["download_index_table"]
    download_index_geom_table = s2_index_cfg["download_index_geom_table"]
    metadata_source_table = s2_index_cfg["metadata_source_table"]

    sql_parts = []
    if drop_existing:
        sql_parts.append(f"DROP TABLE IF EXISTS {download_index_geom_table};")

    sql_parts.append(
        f"""
        CREATE TABLE {download_index_geom_table} AS
        SELECT
            LEFT(sdi.file_name, LENGTH(sdi.file_name) - 4) AS product_name,
            sdi.file_name,
            sdi.sensing_time,
            sm.*
        FROM {download_index_table} sdi
        JOIN {metadata_source_table} sm
          ON LEFT(sdi.file_name, LENGTH(sdi.file_name) - 4) = sm.name;
        """
    )

    sensing_index_name = _safe_index_name(download_index_geom_table, "sensing_time_idx")
    geom_index_name = _safe_index_name(download_index_geom_table, "geom_idx")

    sql_parts.append(
        f"""
        CREATE INDEX IF NOT EXISTS {sensing_index_name}
        ON {download_index_geom_table}(sensing_time);
        """
    )

    sql_parts.append(
        f"""
        CREATE INDEX IF NOT EXISTS {geom_index_name}
        ON {download_index_geom_table}
        USING GIST (geom);
        """
    )

    full_sql = "\n".join(sql_parts)
    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(full_sql)
            conn.commit()

    print(f"sentinel2_download_index_geom_table={download_index_geom_table}")
