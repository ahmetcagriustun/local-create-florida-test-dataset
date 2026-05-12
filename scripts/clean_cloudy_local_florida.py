from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import numpy as np

try:
    import tifffile as tiff
except Exception as exc:  # pragma: no cover
    raise RuntimeError("tifffile is required for local Florida cloud cleaning.") from exc


def read_tci(path: Path) -> np.ndarray:
    arr = tiff.imread(path)
    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[0] < arr.shape[-1]:
        arr = np.transpose(arr, (1, 2, 0))
    arr = arr.astype(np.float32)
    if arr.max() > 1.0:
        arr /= 255.0 if arr.max() <= 255 else arr.max()
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.shape[2] > 3:
        arr = arr[..., :3]
    return arr


def read_multiband(path: Path) -> np.ndarray:
    arr = tiff.imread(path)
    if arr.ndim == 2:
        arr = arr[..., None]
    elif arr.ndim == 3 and arr.shape[0] < arr.shape[-1] and arr.shape[0] <= 16:
        arr = np.transpose(arr, (1, 2, 0))
    arr = arr.astype(np.float32)
    out = np.empty_like(arr, dtype=np.float32)
    for c in range(arr.shape[2]):
        band = np.nan_to_num(arr[..., c], nan=0.0, posinf=0.0, neginf=0.0)
        lo, hi = np.percentile(band, [2, 98])
        if hi <= lo:
            mn, mx = band.min(), band.max()
            out[..., c] = 0.0 if mx <= mn else (band - mn) / (mx - mn + 1e-6)
        else:
            out[..., c] = np.clip((band - lo) / (hi - lo + 1e-6), 0, 1)
    return out


def estimate_cloud_ratio_from_tci(tci: np.ndarray, bright_thresh: float = 0.8) -> float:
    r, g, b = tci[..., 0], tci[..., 1], tci[..., 2]
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return float((luminance > bright_thresh).mean())


def estimate_cloud_ratio_from_multiband(
    mb: np.ndarray,
    vis_thresh: float = 0.75,
    nir_thresh: float = 0.65,
    ndvi_upper: float = 0.25,
) -> float:
    c = mb.shape[2]
    if c < 4:
        vis = mb.mean(axis=2)
        return float((vis > vis_thresh).mean())
    b02, b03, b04, b08 = mb[..., 0], mb[..., 1], mb[..., 2], mb[..., 3]
    vis = (b02 + b03 + b04) / 3.0
    nir = b08
    ndvi = (b08 - b04) / (b08 + b04 + 1e-6)
    cloud_mask = (vis > vis_thresh) & (nir > nir_thresh) & (ndvi < ndvi_upper)
    return float(cloud_mask.mean())


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create a local cloud-cleaned Florida patch folder with TCI copies.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "outputs" / "florida_6class_patch_manifest.csv",
        help="Patch manifest CSV.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repo_root / "data" / "patches" / "florida_6class_cloudfiltered_review",
        help="Output root with class subfolders containing multiband and TCI patches together.",
    )
    parser.add_argument(
        "--cloudy-root",
        type=Path,
        default=repo_root / "data" / "patches" / "florida_6class_cloudy_review",
        help="Optional root to copy cloudy samples for later inspection.",
    )
    parser.add_argument("--bright-thresh", type=float, default=0.80)
    parser.add_argument("--max-cloud-ratio", type=float, default=0.30)
    parser.add_argument("--vis-thresh", type=float, default=0.75)
    parser.add_argument("--nir-thresh", type=float, default=0.65)
    parser.add_argument("--ndvi-upper", type=float, default=0.25)
    parser.add_argument("--copy-cloudy", action="store_true", help="Also copy cloudy patches into --cloudy-root.")
    return parser.parse_args()


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> None:
    args = parse_args()
    manifest = args.manifest
    repo_root = manifest.parents[1]
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.copy_cloudy:
        args.cloudy_root.mkdir(parents=True, exist_ok=True)

    rows_out: list[dict[str, str | float]] = []
    clean_counts: Counter[str] = Counter()
    cloudy_counts: Counter[str] = Counter()
    examined = 0
    clean = 0
    cloudy = 0

    with manifest.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            examined += 1
            cls = row["target_ship_type"]
            mb_rel = Path(row["multiband_path"])
            tci_rel = Path(row["tci_path"]) if row.get("tci_path") else None
            mb_src = (repo_root / mb_rel).resolve()
            tci_src = (repo_root / tci_rel).resolve() if tci_rel else None

            mode = "MULTIBAND"
            if tci_src and tci_src.exists():
                cloud_ratio = estimate_cloud_ratio_from_tci(read_tci(tci_src), bright_thresh=args.bright_thresh)
                mode = "TCI"
            else:
                cloud_ratio = estimate_cloud_ratio_from_multiband(
                    read_multiband(mb_src),
                    vis_thresh=args.vis_thresh,
                    nir_thresh=args.nir_thresh,
                    ndvi_upper=args.ndvi_upper,
                )

            is_clean = cloud_ratio < args.max_cloud_ratio
            target_root = args.output_root if is_clean else args.cloudy_root
            action = "KEEP"
            if is_clean:
                clean += 1
                clean_counts[cls] += 1
                _copy_if_exists(mb_src, args.output_root / cls / mb_src.name)
                if tci_src:
                    _copy_if_exists(tci_src, args.output_root / cls / tci_src.name)
            else:
                cloudy += 1
                cloudy_counts[cls] += 1
                action = "CLOUDY"
                if args.copy_cloudy:
                    _copy_if_exists(mb_src, target_root / cls / mb_src.name)
                    if tci_src:
                        _copy_if_exists(tci_src, target_root / cls / tci_src.name)

            rows_out.append(
                {
                    "class": cls,
                    "api_id": row["api_id"],
                    "record_id": row["record_id"],
                    "mmsi": row["mmsi"],
                    "mode": mode,
                    "cloud_ratio": round(cloud_ratio, 6),
                    "action": action,
                    "multiband_src": str(mb_src),
                    "tci_src": str(tci_src) if tci_src else "",
                }
            )

    report_csv = manifest.parent / "florida_6class_cloud_clean_report_local.csv"
    with report_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["class", "api_id", "record_id", "mmsi", "mode", "cloud_ratio", "action", "multiband_src", "tci_src"],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    summary = {
        "manifest": str(manifest),
        "output_root": str(args.output_root),
        "cloudy_root": str(args.cloudy_root) if args.copy_cloudy else "",
        "thresholds": {
            "bright_thresh": args.bright_thresh,
            "max_cloud_ratio": args.max_cloud_ratio,
            "vis_thresh": args.vis_thresh,
            "nir_thresh": args.nir_thresh,
            "ndvi_upper": args.ndvi_upper,
        },
        "examined": examined,
        "clean_count": clean,
        "cloudy_count": cloudy,
        "clean_counts_by_class": dict(clean_counts),
        "cloudy_counts_by_class": dict(cloudy_counts),
        "report_csv": str(report_csv),
    }
    summary_json = manifest.parent / "florida_6class_cloud_clean_summary_local.json"
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
