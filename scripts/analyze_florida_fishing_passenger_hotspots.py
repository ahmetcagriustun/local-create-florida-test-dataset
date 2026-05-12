from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass(frozen=True)
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


TARGET_CLASS_ORDER = [
    "Fishing",
    "Passenger",
    "Sailing",
    "Pleasure",
    "CargoTanker",
]


def build_arg_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Analyze NOAA bulk AIS files over a broader Florida region to find hotspots "
            "that can enrich Fishing and Passenger samples before downloading more Sentinel-2 scenes."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root / "config.local.yaml",
        help="Path to config.local.yaml",
    )
    parser.add_argument(
        "--analysis-min-lon",
        type=float,
        default=-87.5,
        help="Broader Florida analysis bbox minimum longitude.",
    )
    parser.add_argument(
        "--analysis-min-lat",
        type=float,
        default=24.0,
        help="Broader Florida analysis bbox minimum latitude.",
    )
    parser.add_argument(
        "--analysis-max-lon",
        type=float,
        default=-79.0,
        help="Broader Florida analysis bbox maximum longitude.",
    )
    parser.add_argument(
        "--analysis-max-lat",
        type=float,
        default=31.5,
        help="Broader Florida analysis bbox maximum latitude.",
    )
    parser.add_argument(
        "--grid-size-deg",
        type=float,
        default=0.5,
        help="Grid resolution in degrees.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=250_000,
        help="Pandas chunksize for NOAA CSV processing.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="How many top cells to keep in each summary file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional explicit output directory.",
    )
    return parser


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def vessel_type_to_target_class(code: Any) -> str | None:
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        return None

    if code_int == 30:
        return "Fishing"
    if 60 <= code_int <= 69:
        return "Passenger"
    if code_int == 36:
        return "Sailing"
    if code_int == 37:
        return "Pleasure"
    if 70 <= code_int <= 89:
        return "CargoTanker"
    return None


def make_output_dir(explicit: Path | None, repo_root: Path) -> Path:
    if explicit is not None:
        explicit.mkdir(parents=True, exist_ok=True)
        return explicit
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = repo_root / "outputs" / f"fishing_passenger_hotspot_analysis_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def iter_noaa_files(raw_dir: Path, start_date: str, end_date: str) -> list[Path]:
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


def process_files(
    files: list[Path],
    *,
    bbox: BBox,
    grid_size_deg: float,
    chunksize: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    record_counts: defaultdict[tuple[int, int, str, str], int] = defaultdict(int)
    unique_mmsi_sets: defaultdict[tuple[int, int, str, str], set[str]] = defaultdict(set)
    cell_class_mmsi_sets: defaultdict[tuple[int, int, str], set[str]] = defaultdict(set)

    usecols = ["mmsi", "base_date_time", "latitude", "longitude", "vessel_type"]

    for file_path in files:
        chunk_iter = pd.read_csv(
            file_path,
            compression="zstd",
            usecols=usecols,
            chunksize=chunksize,
            low_memory=False,
        )
        for chunk in chunk_iter:
            chunk = chunk[
                (chunk["longitude"] >= bbox.min_lon)
                & (chunk["longitude"] <= bbox.max_lon)
                & (chunk["latitude"] >= bbox.min_lat)
                & (chunk["latitude"] <= bbox.max_lat)
            ].copy()
            if chunk.empty:
                continue

            chunk["target_class"] = chunk["vessel_type"].map(vessel_type_to_target_class)
            chunk = chunk[chunk["target_class"].notna()].copy()
            if chunk.empty:
                continue

            chunk["date"] = chunk["base_date_time"].astype(str).str.slice(0, 10)
            chunk["cell_x"] = ((chunk["longitude"] - bbox.min_lon) / grid_size_deg).apply(math.floor).astype(int)
            chunk["cell_y"] = ((chunk["latitude"] - bbox.min_lat) / grid_size_deg).apply(math.floor).astype(int)
            chunk["mmsi"] = chunk["mmsi"].astype(str)

            grouped_records = (
                chunk.groupby(["cell_x", "cell_y", "date", "target_class"], observed=True)
                .size()
                .reset_index(name="record_count")
            )
            for row in grouped_records.itertuples(index=False):
                key = (int(row.cell_x), int(row.cell_y), str(row.date), str(row.target_class))
                record_counts[key] += int(row.record_count)

            dedup = chunk[["cell_x", "cell_y", "date", "target_class", "mmsi"]].drop_duplicates()
            grouped_unique = dedup.groupby(["cell_x", "cell_y", "date", "target_class"], observed=True)
            for key, sub_df in grouped_unique:
                cell_x, cell_y, date_str, target_class = key
                unique_mmsi_sets[(int(cell_x), int(cell_y), str(date_str), str(target_class))].update(
                    sub_df["mmsi"].tolist()
                )

            grouped_cell_class = dedup.groupby(["cell_x", "cell_y", "target_class"], observed=True)
            for key, sub_df in grouped_cell_class:
                cell_x, cell_y, target_class = key
                cell_class_mmsi_sets[(int(cell_x), int(cell_y), str(target_class))].update(sub_df["mmsi"].tolist())

    daily_rows: list[dict[str, Any]] = []
    for (cell_x, cell_y, date_str, target_class), count in record_counts.items():
        mmsi_set = unique_mmsi_sets[(cell_x, cell_y, date_str, target_class)]
        daily_rows.append(
            {
                "cell_x": cell_x,
                "cell_y": cell_y,
                "date": date_str,
                "target_class": target_class,
                "record_count": count,
                "unique_mmsi": len(mmsi_set),
            }
        )
    daily_df = pd.DataFrame(daily_rows)

    cell_rows: list[dict[str, Any]] = []
    if daily_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    for (cell_x, cell_y, target_class), mmsi_set in cell_class_mmsi_sets.items():
        daily_subset = daily_df[
            (daily_df["cell_x"] == cell_x)
            & (daily_df["cell_y"] == cell_y)
            & (daily_df["target_class"] == target_class)
        ]
        cell_rows.append(
            {
                "cell_x": cell_x,
                "cell_y": cell_y,
                "target_class": target_class,
                "unique_mmsi_total": len(mmsi_set),
                "unique_mmsi_days": int(daily_subset["unique_mmsi"].sum()),
                "record_count_total": int(daily_subset["record_count"].sum()),
                "active_dates": int(daily_subset["date"].nunique()),
            }
        )
    cell_df = pd.DataFrame(cell_rows)
    return daily_df, cell_df


def add_cell_geometry(df: pd.DataFrame, *, bbox: BBox, grid_size_deg: float) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["cell_min_lon"] = bbox.min_lon + out["cell_x"] * grid_size_deg
    out["cell_max_lon"] = out["cell_min_lon"] + grid_size_deg
    out["cell_min_lat"] = bbox.min_lat + out["cell_y"] * grid_size_deg
    out["cell_max_lat"] = out["cell_min_lat"] + grid_size_deg
    out["cell_center_lon"] = (out["cell_min_lon"] + out["cell_max_lon"]) / 2.0
    out["cell_center_lat"] = (out["cell_min_lat"] + out["cell_max_lat"]) / 2.0
    return out


def build_cell_wide_table(cell_df: pd.DataFrame, *, bbox: BBox, grid_size_deg: float) -> pd.DataFrame:
    if cell_df.empty:
        return cell_df
    wide = (
        cell_df.pivot_table(
            index=["cell_x", "cell_y"],
            columns="target_class",
            values=["unique_mmsi_total", "unique_mmsi_days", "record_count_total", "active_dates"],
            fill_value=0,
        )
        .sort_index(axis=1)
    )
    wide.columns = [f"{metric}_{target_class}" for metric, target_class in wide.columns]
    wide = wide.reset_index()
    wide = add_cell_geometry(wide, bbox=bbox, grid_size_deg=grid_size_deg)

    for class_name in TARGET_CLASS_ORDER:
        for metric in ["unique_mmsi_total", "unique_mmsi_days", "record_count_total", "active_dates"]:
            col = f"{metric}_{class_name}"
            if col not in wide.columns:
                wide[col] = 0

    wide["small_recreation_unique_mmsi_days"] = (
        wide["unique_mmsi_days_Sailing"] + wide["unique_mmsi_days_Pleasure"]
    )
    wide["fishing_plus_passenger_unique_mmsi_days"] = (
        wide["unique_mmsi_days_Fishing"] + wide["unique_mmsi_days_Passenger"]
    )
    wide["other_pressure_unique_mmsi_days"] = (
        wide["small_recreation_unique_mmsi_days"] + wide["unique_mmsi_days_CargoTanker"]
    )
    wide["fishing_enrichment_ratio"] = wide["unique_mmsi_days_Fishing"] / (
        1.0 + wide["small_recreation_unique_mmsi_days"] + wide["unique_mmsi_days_CargoTanker"]
    )
    wide["passenger_enrichment_ratio"] = wide["unique_mmsi_days_Passenger"] / (
        1.0 + wide["small_recreation_unique_mmsi_days"] + wide["unique_mmsi_days_CargoTanker"]
    )
    wide["joint_target_enrichment_ratio"] = wide["fishing_plus_passenger_unique_mmsi_days"] / (
        1.0 + wide["other_pressure_unique_mmsi_days"]
    )
    return wide


def write_ranked_outputs(
    *,
    daily_df: pd.DataFrame,
    cell_wide_df: pd.DataFrame,
    top_k: int,
    out_dir: Path,
) -> dict[str, Any]:
    top_fishing_volume = cell_wide_df.sort_values(
        ["unique_mmsi_days_Fishing", "fishing_enrichment_ratio"], ascending=[False, False]
    ).head(top_k)
    top_passenger_volume = cell_wide_df.sort_values(
        ["unique_mmsi_days_Passenger", "passenger_enrichment_ratio"], ascending=[False, False]
    ).head(top_k)
    top_joint_enriched = cell_wide_df.sort_values(
        ["joint_target_enrichment_ratio", "fishing_plus_passenger_unique_mmsi_days"],
        ascending=[False, False],
    ).head(top_k)

    top_fishing_days = (
        daily_df[daily_df["target_class"] == "Fishing"]
        .sort_values(["unique_mmsi", "record_count"], ascending=[False, False])
        .head(top_k)
    )
    top_passenger_days = (
        daily_df[daily_df["target_class"] == "Passenger"]
        .sort_values(["unique_mmsi", "record_count"], ascending=[False, False])
        .head(top_k)
    )

    top_fishing_volume.to_csv(out_dir / "top_fishing_cells.csv", index=False)
    top_passenger_volume.to_csv(out_dir / "top_passenger_cells.csv", index=False)
    top_joint_enriched.to_csv(out_dir / "top_joint_enriched_cells.csv", index=False)
    top_fishing_days.to_csv(out_dir / "top_fishing_cell_dates.csv", index=False)
    top_passenger_days.to_csv(out_dir / "top_passenger_cell_dates.csv", index=False)

    recommended = {
        "fishing_primary_cell": (
            top_fishing_volume.iloc[0][
                [
                    "cell_min_lon",
                    "cell_min_lat",
                    "cell_max_lon",
                    "cell_max_lat",
                    "unique_mmsi_days_Fishing",
                    "fishing_enrichment_ratio",
                ]
            ].to_dict()
            if not top_fishing_volume.empty
            else None
        ),
        "passenger_primary_cell": (
            top_passenger_volume.iloc[0][
                [
                    "cell_min_lon",
                    "cell_min_lat",
                    "cell_max_lon",
                    "cell_max_lat",
                    "unique_mmsi_days_Passenger",
                    "passenger_enrichment_ratio",
                ]
            ].to_dict()
            if not top_passenger_volume.empty
            else None
        ),
        "joint_enriched_primary_cell": (
            top_joint_enriched.iloc[0][
                [
                    "cell_min_lon",
                    "cell_min_lat",
                    "cell_max_lon",
                    "cell_max_lat",
                    "fishing_plus_passenger_unique_mmsi_days",
                    "joint_target_enrichment_ratio",
                ]
            ].to_dict()
            if not top_joint_enriched.empty
            else None
        ),
    }
    with open(out_dir / "recommended_cells.json", "w", encoding="utf-8") as f:
        json.dump(recommended, f, indent=2)
    return recommended


def main() -> None:
    args = build_arg_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(args.config)
    out_dir = make_output_dir(args.output_dir, repo_root)

    raw_dir = (args.config.parent / cfg["paths"]["raw_dir"]).resolve()
    start_date = str(cfg["study_area"]["start_date"])
    end_date = str(cfg["study_area"]["end_date"])
    files = iter_noaa_files(raw_dir, start_date, end_date)
    if not files:
        raise FileNotFoundError(f"No NOAA bulk AIS files found in {raw_dir} for {start_date} to {end_date}")

    bbox = BBox(
        min_lon=args.analysis_min_lon,
        min_lat=args.analysis_min_lat,
        max_lon=args.analysis_max_lon,
        max_lat=args.analysis_max_lat,
    )

    daily_df, cell_df = process_files(
        files,
        bbox=bbox,
        grid_size_deg=args.grid_size_deg,
        chunksize=args.chunksize,
    )
    if daily_df.empty or cell_df.empty:
        raise RuntimeError("No relevant Fishing/Passenger/Sailing/Pleasure/CargoTanker AIS records found in the analysis area.")

    daily_df = add_cell_geometry(daily_df, bbox=bbox, grid_size_deg=args.grid_size_deg)
    cell_wide_df = build_cell_wide_table(cell_df, bbox=bbox, grid_size_deg=args.grid_size_deg)

    daily_df.to_csv(out_dir / "cell_date_class_summary.csv", index=False)
    cell_df.to_csv(out_dir / "cell_class_long_summary.csv", index=False)
    cell_wide_df.to_csv(out_dir / "cell_summary_wide.csv", index=False)

    recommended = write_ranked_outputs(
        daily_df=daily_df,
        cell_wide_df=cell_wide_df,
        top_k=args.top_k,
        out_dir=out_dir,
    )

    summary = {
        "analysis_bbox": {
            "min_lon": bbox.min_lon,
            "min_lat": bbox.min_lat,
            "max_lon": bbox.max_lon,
            "max_lat": bbox.max_lat,
        },
        "grid_size_deg": args.grid_size_deg,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "n_files": len(files),
        "n_cell_date_class_rows": int(len(daily_df)),
        "n_cell_class_rows": int(len(cell_df)),
        "n_cells": int(cell_wide_df[["cell_x", "cell_y"]].drop_duplicates().shape[0]),
        "recommended_cells": recommended,
    }
    with open(out_dir / "analysis_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Outputs written to: {out_dir}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
