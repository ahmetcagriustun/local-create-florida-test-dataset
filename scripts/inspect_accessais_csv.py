import argparse
from collections import Counter
from pathlib import Path

import pandas as pd


USECOLS = [
    "MMSI",
    "BaseDateTime",
    "LAT",
    "LON",
    "VesselType",
    "Length",
    "Width",
    "Draft",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile a NOAA AccessAIS CSV without loading the entire file into memory."
    )
    parser.add_argument("csv_path", type=Path, help="Path to NOAA AccessAIS CSV")
    parser.add_argument("--chunksize", type=int, default=100_000, help="Pandas chunk size")
    parser.add_argument("--topn", type=int, default=20, help="Top N vessel-type codes to print")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    row_count = 0
    unique_mmsi = set()
    vessel_type_counts: Counter[str] = Counter()
    min_time = None
    max_time = None
    missing_counts = Counter()

    for chunk in pd.read_csv(args.csv_path, usecols=USECOLS, chunksize=args.chunksize):
        row_count += len(chunk)

        unique_mmsi.update(chunk["MMSI"].dropna().astype(str).tolist())

        vessel_codes = pd.to_numeric(chunk["VesselType"], errors="coerce")
        vessel_labels = vessel_codes.apply(
            lambda value: "NA" if pd.isna(value) else str(int(value))
        )
        vessel_type_counts.update(vessel_labels.tolist())

        times = pd.to_datetime(chunk["BaseDateTime"], errors="coerce", utc=True)
        if not times.dropna().empty:
            chunk_min = times.min()
            chunk_max = times.max()
            min_time = chunk_min if min_time is None else min(min_time, chunk_min)
            max_time = chunk_max if max_time is None else max(max_time, chunk_max)

        for col in USECOLS:
            missing_counts[col] += int(chunk[col].isna().sum())

    print(f"file={args.csv_path}")
    print(f"rows={row_count}")
    print(f"unique_mmsi={len(unique_mmsi)}")
    print(f"min_time_utc={min_time}")
    print(f"max_time_utc={max_time}")
    print("top_vessel_types=")
    for code, count in vessel_type_counts.most_common(args.topn):
        print(f"  {code}: {count}")
    print("missing_values=")
    for col in USECOLS:
        print(f"  {col}: {missing_counts[col]}")


if __name__ == "__main__":
    main()
