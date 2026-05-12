from __future__ import annotations

import csv
import gc
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("GDAL_CACHEMAX", "64")
os.environ.setdefault("GDAL_NUM_THREADS", "1")
os.environ.setdefault("RIO_MAX_THREADS", "1")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".jp2,.tif")
os.environ.setdefault("JP2KAK_THREADS", "1")

import numpy as np
import psycopg2
from pyproj.datadir import get_data_dir

_PROJ_DATA_DIR = get_data_dir()
os.environ["PROJ_LIB"] = _PROJ_DATA_DIR
os.environ["PROJ_DATA"] = _PROJ_DATA_DIR

import rasterio
from pyproj import Proj, Transformer
from rasterio.windows import Window


LOGGER = logging.getLogger(__name__)

BAND_SUFFIX = {
    "B02": "_B02_10m.jp2",
    "B03": "_B03_10m.jp2",
    "B04": "_B04_10m.jp2",
    "B08": "_B08_10m.jp2",
    "TCI": "_TCI_10m.jp2",
}


def _connect(pg_cfg: dict):
    return psycopg2.connect(
        host=pg_cfg["host"],
        port=pg_cfg.get("port", 5432),
        dbname=pg_cfg["dbname"],
        user=pg_cfg["user"],
        password=pg_cfg["password"],
    )


def _slug(text: str | None) -> str:
    if text is None:
        return "NA"
    cleaned = re.sub(r"\s+", "_", str(text).strip())
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "", cleaned)
    return cleaned or "NA"


@lru_cache(maxsize=32)
def _utm_proj_from_api_id(api_id: str) -> Proj:
    match = re.search(r"T(?P<zone>\d{2})(?P<band>[C-HJ-NP-X])[A-Z]{2}", api_id)
    if not match:
        raise ValueError(f"Could not infer UTM tile from api_id={api_id}")
    zone = int(match.group("zone"))
    band = match.group("band")
    south = band < "N"
    return Proj(proj="utm", zone=zone, datum="WGS84", units="m", south=south)


def _fetch_api_ids(conn, table: str, target_only: bool = True) -> list[str]:
    sql = f"SELECT DISTINCT api_id FROM {table} WHERE api_id IS NOT NULL"
    if target_only:
        sql += ' AND "Target ship type" IS NOT NULL'
    sql += " ORDER BY api_id;"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def _fetch_api_zip_lookup(conn, table: str) -> dict[str, str]:
    sql = f"""
        SELECT api_id, file_name
        FROM {table}
        WHERE api_id IS NOT NULL
          AND file_name IS NOT NULL;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return {row[0]: row[1] for row in cur.fetchall()}


def _fetch_points_for_api(conn, table: str, api_id: str, limit: int | None = None, target_only: bool = True):
    sql = f"""
        SELECT
            id,
            "MMSI"::text AS mmsi,
            "Ship type" AS detailed_ship_type,
            "Target ship type" AS target_ship_type,
            "Length" AS length,
            api_id,
            sensing_time_without_tz::text AS sensing_time,
            ST_X(geom) AS lon,
            ST_Y(geom) AS lat
        FROM {table}
        WHERE api_id = %s
    """
    if target_only:
        sql += ' AND "Target ship type" IS NOT NULL'
    sql += "\n        ORDER BY id\n"
    if limit is not None:
        sql += " LIMIT %s"

    with conn.cursor() as cur:
        if limit is not None:
            cur.execute(sql, (api_id, limit))
        else:
            cur.execute(sql, (api_id,))
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    return [{key: value for key, value in zip(cols, row)} for row in rows]


def _find_band_members_in_safe_zip(zip_path: Path, want_bands: list[str]) -> dict[str, str]:
    want = set(want_bands)
    found: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        names = zip_ref.namelist()
        for band in want:
            suffix = BAND_SUFFIX.get(band)
            if not suffix:
                continue
            member = next((name for name in names if name.endswith(suffix) and "/IMG_DATA/" in name), None)
            if member:
                found[band] = member
    missing = [band for band in want if band not in found]
    if missing:
        LOGGER.warning("Missing bands in %s: %s", zip_path.name, ",".join(missing))
    return found


def _extract_members(zip_path: Path, members: dict[str, str], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for band, member in members.items():
            dst = out_dir / Path(member).name
            if not dst.exists():
                with zip_ref.open(member) as src, open(dst, "wb") as dst_handle:
                    shutil.copyfileobj(src, dst_handle)
            paths[band] = dst
    return paths


def _lonlat_to_rowcol(src: rasterio.DatasetReader, lon: float, lat: float, api_id: str) -> tuple[int, int]:
    if src.crs is not None:
        transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        x_coord, y_coord = transformer.transform(lon, lat)
    else:
        proj = _utm_proj_from_api_id(api_id)
        x_coord, y_coord = proj(lon, lat)
    row, col = src.index(x_coord, y_coord)
    return int(row), int(col)


def _make_centered_window(row: int, col: int, size_px: int) -> Window:
    half = size_px // 2
    return Window(col - half, row - half, size_px, size_px)


def _write_multiband_geotiff(
    out_path: Path,
    ref_src: rasterio.DatasetReader,
    window: Window,
    arrays: list[np.ndarray],
    dtype: str | None = None,
    meta_tags: dict | None = None,
) -> None:
    transform = ref_src.window_transform(window)
    height = int(window.height)
    width = int(window.width)
    count = len(arrays)
    dtype = dtype or arrays[0].dtype

    profile = ref_src.profile.copy()
    profile.update(
        {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": count,
            "dtype": dtype,
            "transform": transform,
            "compress": "deflate",
            "predictor": 2,
            "tiled": True,
            "blockxsize": min(512, width),
            "blockysize": min(512, height),
            "nodata": 0,
        }
    )

    with rasterio.open(out_path, "w", **profile) as dst:
        for index, array in enumerate(arrays, start=1):
            dst.write(array, index)
        if meta_tags:
            dst.update_tags(**{key: str(value) for key, value in meta_tags.items()})


def _copy_if_needed(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)


def _process_one_product(
    *,
    api_id: str,
    points: list[dict],
    zip_path: Path,
    patch_size_px: int,
    work_dir: Path,
    bands: list[str],
    raw_output_dir: Path,
    class_output_dir: Path,
    tci_output_dir: Path | None,
    tci_in_class_output_dir: bool,
    save_tci: bool,
    skip_existing: bool,
) -> tuple[int, int, list[dict], Counter, list[str]]:
    prod_dir = work_dir / api_id
    made = 0
    skipped = 0
    manifest_rows: list[dict] = []
    class_counts: Counter = Counter()
    warnings: list[str] = []

    if not zip_path.exists():
        warning = f"missing_zip:{zip_path.name}"
        LOGGER.error("Missing Sentinel-2 ZIP for %s at %s", api_id, zip_path)
        return made, skipped, manifest_rows, class_counts, [warning]

    try:
        want = [band for band in bands if band != "TCI"] + (["TCI"] if save_tci else [])
        members = _find_band_members_in_safe_zip(zip_path, want)
        required_bands = [band for band in bands if band != "TCI"]
        if any(band not in members for band in required_bands):
            warning = f"missing_required_bands:{api_id}"
            LOGGER.error("Missing required 10m bands in %s; skipping product.", api_id)
            return made, skipped, manifest_rows, class_counts, [warning]

        extracted = _extract_members(zip_path, members, prod_dir)

        with ExitStack() as stack:
            ref = stack.enter_context(rasterio.open(extracted[bands[0]]))
            band_srcs = {band: stack.enter_context(rasterio.open(extracted[band])) for band in required_bands}
            tci_src = None
            if save_tci and "TCI" in extracted:
                tci_src = stack.enter_context(rasterio.open(extracted["TCI"]))

            for rec in points:
                target_ship_type = rec.get("target_ship_type")
                if not target_ship_type:
                    skipped += 1
                    continue

                rec_id = rec["id"]
                mmsi = rec["mmsi"]
                lon = float(rec["lon"])
                lat = float(rec["lat"])

                base = f"{_slug(target_ship_type)}_{_slug(mmsi)}_{rec_id}"
                mb_name = f"{base}.tif"
                tci_name = f"{base}_TCI.tif"

                raw_mb_path = raw_output_dir / api_id / mb_name
                class_mb_path = class_output_dir / target_ship_type / mb_name
                if save_tci:
                    if tci_in_class_output_dir:
                        tci_path = class_output_dir / target_ship_type / tci_name
                    else:
                        tci_path = tci_output_dir / target_ship_type / tci_name if tci_output_dir else None
                else:
                    tci_path = None

                if skip_existing and class_mb_path.exists() and (not save_tci or (tci_path and tci_path.exists())):
                    skipped += 1
                    continue

                try:
                    row, col = _lonlat_to_rowcol(ref, lon, lat, api_id)
                    window = _make_centered_window(row, col, patch_size_px)
                except Exception as exc:
                    warning = f"indexing_error:{api_id}:{rec_id}:{exc}"
                    LOGGER.warning("Indexing error for %s record %s: %s", api_id, rec_id, exc)
                    warnings.append(warning)
                    continue

                arrays = [band_srcs[band].read(1, window=window, boundless=True, fill_value=0) for band in required_bands]
                local_mb = prod_dir / mb_name
                meta_tags = {
                    "api_id": api_id,
                    "mmsi": mmsi,
                    "ship_type": rec.get("detailed_ship_type", ""),
                    "target_ship_type": target_ship_type,
                    "lon": lon,
                    "lat": lat,
                    "record_id": rec_id,
                    "sensing_time": rec.get("sensing_time", ""),
                    "bands": ",".join(required_bands),
                }
                _write_multiband_geotiff(local_mb, ref, window, arrays, meta_tags=meta_tags)
                del arrays

                _copy_if_needed(local_mb, raw_mb_path)
                _copy_if_needed(local_mb, class_mb_path)

                tci_written = ""
                if tci_src is not None and tci_path is not None:
                    local_tci = prod_dir / tci_name
                    tci_arr = tci_src.read(window=window, boundless=True, fill_value=0)
                    _write_multiband_geotiff(
                        local_tci,
                        tci_src,
                        window,
                        [tci_arr[0], tci_arr[1], tci_arr[2]],
                        meta_tags=meta_tags,
                    )
                    del tci_arr
                    _copy_if_needed(local_tci, tci_path)
                    tci_written = str(tci_path)
                    try:
                        local_tci.unlink()
                    except Exception:
                        pass

                try:
                    local_mb.unlink()
                except Exception:
                    pass

                manifest_rows.append(
                    {
                        "api_id": api_id,
                        "record_id": rec_id,
                        "mmsi": mmsi,
                        "target_ship_type": target_ship_type,
                        "detailed_ship_type": rec.get("detailed_ship_type", ""),
                        "sensing_time": rec.get("sensing_time", ""),
                        "multiband_path": str(class_mb_path),
                        "raw_multiband_path": str(raw_mb_path),
                        "tci_path": tci_written,
                    }
                )
                class_counts[target_ship_type] += 1
                made += 1
    finally:
        try:
            shutil.rmtree(prod_dir, ignore_errors=True)
        except Exception:
            pass
        gc.collect()

    LOGGER.info("%s -> patches made=%d, skipped=%d", api_id, made, skipped)
    return made, skipped, manifest_rows, class_counts, warnings


def build_patches_local(
    config: dict,
    *,
    table: str | None = None,
    patch_size_px: int | None = None,
    bands: list[str] | None = None,
    save_tci: bool | None = None,
    limit: int | None = None,
    skip_existing: bool | None = None,
) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pg_cfg = config["postgres"]
    paths_cfg = config["paths"]
    patches_cfg = config.get("patches", {})

    source_table = table or patches_cfg.get("source_table", "public.florida_ship_predicted_positions_open_sea")
    target_only = bool(patches_cfg.get("only_target_classes", True))
    selected_bands = bands or list(patches_cfg.get("bands", ["B02", "B03", "B04", "B08"]))
    patch_size = int(patch_size_px or patches_cfg.get("patch_size_px", 128))
    save_tci_flag = bool(patches_cfg.get("save_tci", True) if save_tci is None else save_tci)
    skip_existing_flag = bool(patches_cfg.get("skip_existing", True) if skip_existing is None else skip_existing)

    sentinel2_dir = Path(paths_cfg["sentinel2_dir"])
    raw_output_dir = Path(patches_cfg.get("raw_output_dir", "./data/patches/florida_6class_raw"))
    class_output_dir = Path(patches_cfg.get("class_output_dir", "./data/patches/florida_6class_by_type"))
    tci_output_dir = Path(patches_cfg.get("tci_output_dir", "./data/patches/florida_6class_tci")) if save_tci_flag else None
    tci_in_class_output_dir = bool(patches_cfg.get("tci_in_class_output_dir", False))
    outputs_dir = Path(paths_cfg.get("outputs_dir", "./outputs"))
    manifest_path = Path(patches_cfg.get("manifest_path", outputs_dir / "florida_6class_patch_manifest.csv"))
    summary_path = Path(patches_cfg.get("summary_path", outputs_dir / "florida_6class_patch_summary.json"))
    work_dir_cfg = patches_cfg.get("work_dir")
    api_zip_lookup_table = config.get("sentinel2_index", {}).get(
        "download_index_geom_table",
        "public.florida_sentinel_download_index_geom",
    )

    raw_output_dir.mkdir(parents=True, exist_ok=True)
    class_output_dir.mkdir(parents=True, exist_ok=True)
    if tci_output_dir is not None and not tci_in_class_output_dir:
        tci_output_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    with _connect(pg_cfg) as conn:
        api_ids = _fetch_api_ids(conn, source_table, target_only=target_only)
        api_zip_lookup = _fetch_api_zip_lookup(conn, api_zip_lookup_table)
        LOGGER.info("Found %d api_id values in %s", len(api_ids), source_table)

        total_requested = 0
        total_made = 0
        total_skipped = 0
        total_missing_products = 0
        counts_by_class: Counter = Counter()
        manifest_rows: list[dict] = []
        warnings: list[str] = []

        work_dir = Path(work_dir_cfg) if work_dir_cfg else Path(tempfile.mkdtemp(prefix="florida_s2patch_"))
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            for api_id in api_ids:
                points = _fetch_points_for_api(conn, source_table, api_id, limit=limit, target_only=target_only)
                if not points:
                    continue
                total_requested += len(points)
                zip_name = api_zip_lookup.get(api_id)
                zip_path = sentinel2_dir / zip_name if zip_name else sentinel2_dir / f"{api_id}.zip"
                made, skipped, product_manifest, product_counts, product_warnings = _process_one_product(
                    api_id=api_id,
                    points=points,
                    zip_path=zip_path,
                    patch_size_px=patch_size,
                    work_dir=work_dir,
                    bands=selected_bands,
                    raw_output_dir=raw_output_dir,
                    class_output_dir=class_output_dir,
                    tci_output_dir=tci_output_dir,
                    tci_in_class_output_dir=tci_in_class_output_dir,
                    save_tci=save_tci_flag,
                    skip_existing=skip_existing_flag,
                )
                total_made += made
                total_skipped += skipped
                manifest_rows.extend(product_manifest)
                counts_by_class.update(product_counts)
                warnings.extend(product_warnings)
                total_missing_products += sum(1 for item in product_warnings if item.startswith("missing_zip:"))
                del points
                gc.collect()
        finally:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "api_id",
                "record_id",
                "mmsi",
                "target_ship_type",
                "detailed_ship_type",
                "sensing_time",
                "multiband_path",
                "raw_multiband_path",
                "tci_path",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    summary = {
        "source_table": source_table,
        "target_only": target_only,
        "patch_size_px": patch_size,
        "bands": selected_bands,
        "save_tci": save_tci_flag,
        "api_id_count": len(api_ids),
        "requested_points": total_requested,
        "patches_written": total_made,
        "patches_skipped": total_skipped,
        "missing_product_count": total_missing_products,
        "counts_by_class": dict(sorted(counts_by_class.items())),
        "manifest_path": str(manifest_path),
        "class_output_dir": str(class_output_dir),
        "raw_output_dir": str(raw_output_dir),
        "tci_output_dir": str(class_output_dir) if tci_in_class_output_dir else (str(tci_output_dir) if tci_output_dir else ""),
        "tci_in_class_output_dir": tci_in_class_output_dir,
        "warnings": warnings[:200],
    }

    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(f"patch_source_table={source_table}")
    print(f"api_id_count={len(api_ids)}")
    print(f"requested_points={total_requested}")
    print(f"patches_written={total_made}")
    print(f"patches_skipped={total_skipped}")
    print(f"missing_product_count={total_missing_products}")
    print(f"class_output_dir={class_output_dir}")
    print(f"manifest_path={manifest_path}")
    print(f"summary_path={summary_path}")
    return summary
