import argparse
from pathlib import Path

import pandas as pd


TARGET_CLASS_MAP = {
    30: "Fishing",
    36: "Sailing",
    37: "Pleasure",
    60: "Passenger",
    61: "Passenger",
    62: "Passenger",
    63: "Passenger",
    64: "Passenger",
    65: "Passenger",
    66: "Passenger",
    67: "Passenger",
    68: "Passenger",
    69: "Passenger",
    70: "Cargo",
    71: "Cargo",
    72: "Cargo",
    73: "Cargo",
    74: "Cargo",
    75: "Cargo",
    76: "Cargo",
    77: "Cargo",
    78: "Cargo",
    79: "Cargo",
    80: "Tanker",
    81: "Tanker",
    82: "Tanker",
    83: "Tanker",
    84: "Tanker",
    85: "Tanker",
    86: "Tanker",
    87: "Tanker",
    88: "Tanker",
    89: "Tanker",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize NOAA AccessAIS CSV files into a canonical tabular schema."
    )
    parser.add_argument("csv_path", type=Path, help="Path to NOAA AccessAIS CSV")
    parser.add_argument("output_path", type=Path, help="Output CSV path")
    parser.add_argument("--chunksize", type=int, default=100_000, help="Pandas chunk size")
    return parser


def normalize_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    normalized = pd.DataFrame(
        {
            "source": "NOAA_AccessAIS",
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
            "vessel_type_code": pd.to_numeric(chunk["VesselType"], errors="coerce").astype("Int64"),
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


def main() -> None:
    args = build_parser().parse_args()
    args.output_path.parent.mkdir(parents=True, exist_ok=True)

    first_chunk = True
    for chunk in pd.read_csv(args.csv_path, chunksize=args.chunksize):
        normalized = normalize_chunk(chunk)
        normalized.to_csv(
            args.output_path,
            mode="w" if first_chunk else "a",
            header=first_chunk,
            index=False,
        )
        first_chunk = False

    print(f"normalized_csv={args.output_path}")


if __name__ == "__main__":
    main()
