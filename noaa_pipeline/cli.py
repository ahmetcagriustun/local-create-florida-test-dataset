from __future__ import annotations

import argparse

from .config_utils import load_config
from .download import download_files, print_download_plan
from .filtering import filter_raw_files, merge_filtered_files
from .ais_postgres import import_ship_raw_data_florida
from .postgres import import_csv_to_postgres
from .patches_local import build_patches_local
from .sentinel2_download import download_selected_products, estimate_selected_download_gb
from .sentinel2_index import build_local_download_index, build_local_download_index_geom
from .sentinel2_metadata import fetch_and_store_sentinel2_metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NOAA bulk AIS local workflow")
    parser.add_argument(
        "--config",
        default="config.example.yaml",
        help="Path to YAML config file",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plan-download", help="Print planned NOAA bulk download jobs")
    sub.add_parser("download", help="Download daily NOAA bulk AIS files")
    sub.add_parser("filter-aoi", help="Filter raw NOAA files to the configured AOI")

    merge = sub.add_parser("merge-filtered", help="Merge filtered daily files")
    merge.add_argument(
        "--output-name",
        default="south_florida_2023h1_merged.csv.gz",
        help="Merged output file name",
    )

    import_pg = sub.add_parser("import-postgres", help="Import merged CSV into PostgreSQL")
    import_pg.add_argument(
        "--csv-path",
        default=None,
        help="Optional explicit CSV path to import",
    )
    import_pg.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate the destination table before import",
    )

    s2_meta = sub.add_parser(
        "fetch-s2-metadata",
        help="Fetch Sentinel-2 metadata from CDSE OData and store it in PostgreSQL",
    )
    s2_meta.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate the destination metadata table before insert",
    )

    sub.add_parser(
        "estimate-s2-download",
        help="Estimate total size of the selected Sentinel-2 product download set",
    )
    sub.add_parser(
        "download-s2-selected",
        help="Download selected Sentinel-2 products locally from CDSE",
    )

    s2_index = sub.add_parser(
        "build-s2-download-index",
        help="Build the local Sentinel-2 download index table from downloaded ZIP files",
    )
    s2_index.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate the destination download index table before insert",
    )

    s2_index_geom = sub.add_parser(
        "build-s2-download-index-geom",
        help="Build the Florida Sentinel-2 geometry index table by joining the local download index with metadata",
    )
    s2_index_geom.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep the existing geometry table instead of dropping and recreating it",
    )

    ais_pg = sub.add_parser(
        "import-ship-raw-florida",
        help="Import only the South Florida AIS records for the Sentinel-2 acquisition dates into PostgreSQL",
    )
    ais_pg.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate ship_raw_data_florida before import",
    )

    patch_build = sub.add_parser(
        "build-patches-6class",
        help="Build local Sentinel-2 ship patches for the six mapped Florida target classes",
    )
    patch_build.add_argument(
        "--table",
        default=None,
        help='Override source table (default: config patches.source_table or public.florida_ship_predicted_positions_open_sea)',
    )
    patch_build.add_argument(
        "--patch-size-px",
        type=int,
        default=None,
        help="Override patch size in pixels",
    )
    patch_build.add_argument(
        "--bands",
        nargs="+",
        default=None,
        help="Override 10 m bands to stack, for example B02 B03 B04 B08",
    )
    patch_build.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional per-product point limit for smoke tests",
    )
    patch_build.add_argument(
        "--no-save-tci",
        action="store_true",
        help="Do not save RGB TCI preview patches",
    )
    patch_build.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Rewrite patches even if target files already exist",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "plan-download":
        print_download_plan(config)
    elif args.command == "download":
        download_files(config)
    elif args.command == "filter-aoi":
        filter_raw_files(config)
    elif args.command == "merge-filtered":
        merge_filtered_files(config, output_name=args.output_name)
    elif args.command == "import-postgres":
        import_csv_to_postgres(config, csv_path=args.csv_path, truncate=args.truncate)
    elif args.command == "fetch-s2-metadata":
        fetch_and_store_sentinel2_metadata(config, truncate=args.truncate)
    elif args.command == "estimate-s2-download":
        count, total_gb = estimate_selected_download_gb(config)
        print(f"selected_scene_count={count}")
        print(f"estimated_total_gb={total_gb:.2f}")
    elif args.command == "download-s2-selected":
        download_selected_products(config)
    elif args.command == "build-s2-download-index":
        build_local_download_index(config, truncate=args.truncate)
    elif args.command == "build-s2-download-index-geom":
        build_local_download_index_geom(config, drop_existing=not args.keep_existing)
    elif args.command == "import-ship-raw-florida":
        import_ship_raw_data_florida(config, truncate=args.truncate)
    elif args.command == "build-patches-6class":
        build_patches_local(
            config,
            table=args.table,
            patch_size_px=args.patch_size_px,
            bands=args.bands,
            save_tci=not args.no_save_tci,
            limit=args.limit,
            skip_existing=not args.no_skip_existing,
        )
    else:
        raise ValueError(f"Unknown command: {args.command}")
