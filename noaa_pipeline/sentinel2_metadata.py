from __future__ import annotations

from datetime import datetime, timedelta
import time
from typing import Any

import psycopg2
import requests
from psycopg2.extras import Json, execute_values


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    product_id TEXT PRIMARY KEY,
    name TEXT,
    collection_name TEXT,
    product_type TEXT,
    sensing_start TIMESTAMPTZ,
    sensing_end TIMESTAMPTZ,
    publication_date TIMESTAMPTZ,
    modification_date TIMESTAMPTZ,
    origin_date TIMESTAMPTZ,
    online BOOLEAN,
    s3_path TEXT,
    footprint_wkt TEXT,
    geofootprint_json JSONB,
    cloud_cover DOUBLE PRECISION,
    content_length_bytes BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


UPSERT_SQL_TEMPLATE = """
INSERT INTO {schema}.{table} (
    product_id,
    name,
    collection_name,
    product_type,
    sensing_start,
    sensing_end,
    publication_date,
    modification_date,
    origin_date,
    online,
    s3_path,
    footprint_wkt,
    geofootprint_json,
    cloud_cover,
    content_length_bytes
)
VALUES %s
ON CONFLICT (product_id) DO UPDATE SET
    name = EXCLUDED.name,
    collection_name = EXCLUDED.collection_name,
    product_type = EXCLUDED.product_type,
    sensing_start = EXCLUDED.sensing_start,
    sensing_end = EXCLUDED.sensing_end,
    publication_date = EXCLUDED.publication_date,
    modification_date = EXCLUDED.modification_date,
    origin_date = EXCLUDED.origin_date,
    online = EXCLUDED.online,
    s3_path = EXCLUDED.s3_path,
    footprint_wkt = EXCLUDED.footprint_wkt,
    geofootprint_json = EXCLUDED.geofootprint_json,
    cloud_cover = EXCLUDED.cloud_cover,
    content_length_bytes = EXCLUDED.content_length_bytes;
"""


def _connect(pg_cfg: dict):
    return psycopg2.connect(
        host=pg_cfg["host"],
        port=pg_cfg.get("port", 5432),
        dbname=pg_cfg["dbname"],
        user=pg_cfg["user"],
        password=pg_cfg["password"],
    )


def _bbox_to_wkt_polygon(bbox_cfg: dict) -> str:
    min_lon = float(bbox_cfg["min_lon"])
    min_lat = float(bbox_cfg["min_lat"])
    max_lon = float(bbox_cfg["max_lon"])
    max_lat = float(bbox_cfg["max_lat"])
    return (
        f"POLYGON(("
        f"{min_lon} {min_lat},"
        f"{max_lon} {min_lat},"
        f"{max_lon} {max_lat},"
        f"{min_lon} {max_lat},"
        f"{min_lon} {min_lat}"
        f"))"
    )


def _project_area_table_to_wkt_polygon(
    pg_cfg: dict,
    area_table: str,
    geometry_mode: str = "exact",
) -> str:
    geometry_sql = """
        ST_Multi(
            ST_CollectionExtract(
                ST_MakeValid(
                    ST_Transform(ST_Union(geom), 4326)
                ),
                3
            )
        )
    """
    if geometry_mode == "envelope":
        geometry_sql = f"ST_Envelope({geometry_sql})"
    elif geometry_mode != "exact":
        raise ValueError(f"Unsupported sentinel2_metadata.project_area_filter_mode: {geometry_mode}")

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ST_AsText(
                    {geometry_sql}
                )
                FROM {area_table};
                """
            )
            row = cur.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(f"Could not resolve polygon geometry from area table: {area_table}")
    return str(row[0])


def _resolve_filter_geometry_wkt(config: dict) -> str:
    s2_cfg = config["sentinel2_metadata"]
    area_table = s2_cfg.get("project_area_table")
    if area_table:
        geometry_mode = str(s2_cfg.get("project_area_filter_mode", "exact")).strip().lower()
        return _project_area_table_to_wkt_polygon(
            config["postgres"],
            area_table,
            geometry_mode=geometry_mode,
        )
    study_area = config["study_area"]
    return _bbox_to_wkt_polygon(study_area["bbox"])


def _build_filter(config: dict) -> str:
    s2_cfg = config["sentinel2_metadata"]
    study_area = config["study_area"]
    polygon_wkt = _resolve_filter_geometry_wkt(config)
    start_date = datetime.strptime(study_area["start_date"], "%Y-%m-%d").date()
    end_date = datetime.strptime(study_area["end_date"], "%Y-%m-%d").date() + timedelta(days=1)
    collection_name = s2_cfg.get("collection_name", "SENTINEL-2")
    product_type = s2_cfg.get("product_type", "S2MSI2A")

    return (
        f"Collection/Name eq '{collection_name}' "
        f"and Attributes/OData.CSC.StringAttribute/any(att:"
        f"att/Name eq 'productType' and "
        f"att/OData.CSC.StringAttribute/Value eq '{product_type}') "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{polygon_wkt}') "
        f"and ContentDate/Start gt {start_date.isoformat()}T00:00:00.000Z "
        f"and ContentDate/Start lt {end_date.isoformat()}T00:00:00.000Z"
    )


def _extract_attribute(attributes: list[dict[str, Any]] | None, name: str) -> Any:
    if not attributes:
        return None
    for item in attributes:
        if item.get("Name") == name and "Value" in item:
            return item["Value"]
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_product(product: dict) -> dict[str, Any]:
    attributes = product.get("Attributes") or []
    content_date = product.get("ContentDate") or {}

    product_type = _extract_attribute(attributes, "productType")
    cloud_cover = _extract_attribute(attributes, "cloudCover")

    try:
        cloud_cover = float(cloud_cover) if cloud_cover is not None else None
    except (TypeError, ValueError):
        cloud_cover = None

    try:
        content_length = int(product.get("ContentLength")) if product.get("ContentLength") is not None else None
    except (TypeError, ValueError):
        content_length = None

    return {
        "product_id": product.get("Id"),
        "name": product.get("Name"),
        "collection_name": None,
        "product_type": product_type,
        "sensing_start": _parse_datetime(content_date.get("Start")),
        "sensing_end": _parse_datetime(content_date.get("End")),
        "publication_date": _parse_datetime(product.get("PublicationDate")),
        "modification_date": _parse_datetime(product.get("ModificationDate")),
        "origin_date": _parse_datetime(product.get("OriginDate")),
        "online": product.get("Online"),
        "s3_path": product.get("S3Path"),
        "footprint_wkt": product.get("Footprint"),
        "geofootprint_json": product.get("GeoFootprint"),
        "cloud_cover": cloud_cover,
        "content_length_bytes": content_length,
    }


def _fetch_page(
    endpoint: str,
    params: dict,
    timeout: int,
    session: requests.Session | None = None,
    max_attempts: int = 5,
    retry_backoff_seconds: float = 3.0,
) -> dict:
    client = session or requests
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            sleep_seconds = retry_backoff_seconds * attempt
            print(
                f"sentinel2_metadata_retry attempt={attempt}/{max_attempts} "
                f"sleep_seconds={sleep_seconds:.1f} reason={exc}"
            )
            time.sleep(sleep_seconds)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Sentinel-2 metadata page fetch failed without a captured exception.")


def _iter_products(config: dict):
    s2_cfg = config["sentinel2_metadata"]
    endpoint = s2_cfg["endpoint"]
    top = int(s2_cfg.get("top", 100))
    timeout = int(s2_cfg.get("request_timeout_seconds", 120))
    max_attempts = int(s2_cfg.get("request_max_attempts", 5))
    retry_backoff_seconds = float(s2_cfg.get("request_retry_backoff_seconds", 3.0))
    filter_expr = _build_filter(config)

    skip = 0
    with requests.Session() as session:
        while True:
            params = {
                "$filter": filter_expr,
                "$expand": "Attributes",
                "$top": top,
                "$skip": skip,
                "$orderby": "ContentDate/Start asc",
            }
            payload = _fetch_page(
                endpoint,
                params=params,
                timeout=timeout,
                session=session,
                max_attempts=max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            products = payload.get("value", [])
            if not products:
                break

            for product in products:
                yield product

            skip += len(products)
            print(f"sentinel2_metadata_page_complete skip={skip} page_size={len(products)}")
            if len(products) < top:
                break


def _maybe_enable_postgis(cur) -> bool:
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        return True
    except Exception:
        return False


def _ensure_geom_column(cur, schema: str, table: str) -> None:
    cur.execute(
        f"""
        ALTER TABLE {schema}.{table}
        ADD COLUMN IF NOT EXISTS geom geometry(Geometry, 4326);
        """
    )
    cur.execute(
        f"""
        UPDATE {schema}.{table}
        SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geofootprint_json::text), 4326)
        WHERE geofootprint_json IS NOT NULL AND geom IS NULL;
        """
    )


def fetch_and_store_sentinel2_metadata(config: dict, truncate: bool = False) -> int:
    pg_cfg = config["postgres"]
    s2_cfg = config["sentinel2_metadata"]
    schema = s2_cfg.get("schema", pg_cfg.get("schema", "public"))
    table = s2_cfg["table"]
    max_cloud_cover = s2_cfg.get("max_cloud_cover")

    rows = []
    for raw_product in _iter_products(config):
        normalized = _normalize_product(raw_product)
        if not normalized["collection_name"]:
            normalized["collection_name"] = s2_cfg.get("collection_name", "SENTINEL-2")
        if max_cloud_cover is not None and normalized["cloud_cover"] is not None:
            if float(normalized["cloud_cover"]) > float(max_cloud_cover):
                continue
        rows.append(normalized)

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(schema=schema, table=table))
            if truncate:
                cur.execute(f"TRUNCATE TABLE {schema}.{table};")
            conn.commit()

            if rows:
                values = [
                    (
                        row["product_id"],
                        row["name"],
                        row["collection_name"],
                        row["product_type"],
                        row["sensing_start"],
                        row["sensing_end"],
                        row["publication_date"],
                        row["modification_date"],
                        row["origin_date"],
                        row["online"],
                        row["s3_path"],
                        row["footprint_wkt"],
                        Json(row["geofootprint_json"]) if row["geofootprint_json"] is not None else None,
                        row["cloud_cover"],
                        row["content_length_bytes"],
                    )
                    for row in rows
                ]
                execute_values(
                    cur,
                    UPSERT_SQL_TEMPLATE.format(schema=schema, table=table),
                    values,
                    page_size=500,
                )
                conn.commit()

            postgis_ok = _maybe_enable_postgis(cur)
            if postgis_ok:
                _ensure_geom_column(cur, schema, table)
                conn.commit()

    print(f"sentinel2_metadata_rows={len(rows)}")
    print(f"sentinel2_metadata_table={schema}.{table}")
    return len(rows)
