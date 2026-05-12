from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config_utils import ensure_dir
from .targets import TARGET_CLASS_MAP


USECOLS = [
    "MMSI",
    "BaseDateTime",
    "LAT",
    "LON",
    "SOG",
    "COG",
    "Heading",
    "VesselName",
    "IMO",
    "CallSign",
    "VesselType",
    "Status",
    "Length",
    "Width",
    "Draft",
    "Cargo",
    "TransceiverClass",
]


def _filtered_output_path(filtered_dir: Path, raw_path: Path, compression: str) -> Path:
    stem = raw_path.name.replace(".csv.zst", "")
    suffix = ".csv.gz" if compression == "gzip" else ".csv"
    return filtered_dir / f"{stem}_bbox_filtered{suffix}"


def _normalize_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    vessel_type_codes = pd.to_numeric(chunk["VesselType"], errors="coerce").astype("Int64")
    normalized = pd.DataFrame(
        {
            "source_mmsi": chunk["MMSI"].astype("string"),
            "timestamp_utc": pd.to_datetime(chunk["BaseDateTime"], errors="coerce", utc=True),
            "lat": pd.to_numeric(chunk["LAT"], errors="coerce"),
            "lon": pd.to_numeric(chunk["LON"], errors="coerce"),
            "sog": pd.to_numeric(chunk["SOG"], errors="coerce"),
            "cog": pd.to_numeric(chunk["COG"], errors="coerce"),
            "heading": pd.to_numeric(chunk["Heading"], errors="coerce"),
            "vessel_name": chunk["VesselName"].astype("string"),
            "imo": chunk["IMO"].astype("string"),
            "call_sign": chunk["CallSign"].astype("string"),
            "vessel_type_code": vessel_type_codes,
            "status_code": pd.to_numeric(chunk["Status"], errors="coerce").astype("Int64"),
            "length_m": pd.to_numeric(chunk["Length"], errors="coerce"),
            "width_m": pd.to_numeric(chunk["Width"], errors="coerce"),
            "draft_m": pd.to_numeric(chunk["Draft"], errors="coerce"),
            "cargo_code": pd.to_numeric(chunk["Cargo"], errors="coerce").astype("Int64"),
            "transceiver_class": chunk["TransceiverClass"].astype("string"),
        }
    )
    normalized["target_class_6"] = normalized["vessel_type_code"].map(TARGET_CLASS_MAP)
    return normalized


def filter_raw_files(config: dict) -> None:
    raw_dir = Path(config["paths"]["raw_dir"])
    filtered_dir = ensure_dir(config["paths"]["filtered_dir"])
    filter_cfg = config["filtering"]
    study_area = config["study_area"]

    chunksize = int(filter_cfg.get("chunksize", 200000))
    compression = filter_cfg.get("output_compression", "gzip")
    keep_targets_only = bool(filter_cfg.get("keep_only_target_vessel_types", True))
    target_codes = set(filter_cfg.get("target_codes", []))

    min_lon = float(study_area["bbox"]["min_lon"])
    min_lat = float(study_area["bbox"]["min_lat"])
    max_lon = float(study_area["bbox"]["max_lon"])
    max_lat = float(study_area["bbox"]["max_lat"])

    raw_files = sorted(raw_dir.glob("ais-*.csv.zst"))
    if not raw_files:
        raise FileNotFoundError(f"No raw NOAA files found in {raw_dir}")

    for raw_path in raw_files:
        out_path = _filtered_output_path(filtered_dir, raw_path, compression)
        print(f"filtering={raw_path.name}")

        first_chunk = True
        kept_rows = 0
        for chunk in pd.read_csv(
            raw_path,
            usecols=USECOLS,
            chunksize=chunksize,
            compression="zstd",
        ):
            normalized = _normalize_chunk(chunk)

            bbox_mask = (
                normalized["lon"].between(min_lon, max_lon, inclusive="both")
                & normalized["lat"].between(min_lat, max_lat, inclusive="both")
            )
            filtered = normalized.loc[bbox_mask].copy()

            if keep_targets_only:
                filtered = filtered[filtered["vessel_type_code"].isin(target_codes)]

            filtered = filtered.dropna(subset=["timestamp_utc", "lat", "lon", "source_mmsi"])
            if filtered.empty:
                continue

            filtered.to_csv(
                out_path,
                mode="w" if first_chunk else "a",
                header=first_chunk,
                index=False,
                compression=compression if compression != "none" else None,
            )
            first_chunk = False
            kept_rows += len(filtered)

        print(f"saved={out_path} rows={kept_rows}")


def merge_filtered_files(config: dict, output_name: str = "south_florida_2023h1_merged.csv.gz") -> Path:
    filtered_dir = Path(config["paths"]["filtered_dir"])
    merged_dir = ensure_dir(config["paths"]["merged_dir"])
    out_path = merged_dir / output_name

    files = sorted(filtered_dir.glob("*.csv")) + sorted(filtered_dir.glob("*.csv.gz"))
    if not files:
        raise FileNotFoundError(f"No filtered files found in {filtered_dir}")

    first_chunk = True
    total_rows = 0
    for path in files:
        compression = "gzip" if path.suffix == ".gz" else None
        df = pd.read_csv(path, compression=compression)
        df.to_csv(
            out_path,
            mode="w" if first_chunk else "a",
            header=first_chunk,
            index=False,
            compression="gzip",
        )
        first_chunk = False
        total_rows += len(df)

    print(f"merged={out_path} rows={total_rows}")
    return out_path
