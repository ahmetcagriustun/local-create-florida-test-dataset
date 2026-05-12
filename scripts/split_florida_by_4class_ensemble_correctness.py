from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd


def find_latest_runs(eval_root: Path) -> list[Path]:
    candidates = sorted(eval_root.glob("aws_4class_resnet18_florida_eval_fold*_20*"))
    latest_by_fold: dict[int, Path] = {}
    for run in candidates:
        fold = int(run.name.split("_fold")[1][:2])
        if fold not in latest_by_fold or run.name > latest_by_fold[fold].name:
            latest_by_fold[fold] = run
    return [latest_by_fold[idx] for idx in sorted(latest_by_fold)]


def load_ensemble_predictions(runs: list[Path]) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    classes: list[str] | None = None

    for run in runs:
        fold = int(run.name.split("_fold")[1][:2])
        pred_path = run / "florida_test_predictions.csv"
        df = pd.read_csv(pred_path).sort_values("sample_path").reset_index(drop=True)
        prob_cols = sorted(col for col in df.columns if col.startswith("prob_"))
        current_classes = [col.replace("prob_", "", 1) for col in prob_cols]
        if classes is None:
            classes = current_classes
        elif classes != current_classes:
            raise ValueError(f"Inconsistent class order in {pred_path}")

        keep_cols = ["sample_path", "sample_name", "tci_path", "true_label", "true_label_idx"] + prob_cols
        df = df[keep_cols].copy()
        df = df.rename(columns={col: f"{col}_fold{fold:02d}" for col in prob_cols})

        if merged is None:
            merged = df
        else:
            merged = merged.merge(
                df,
                on=["sample_path", "sample_name", "tci_path", "true_label", "true_label_idx"],
                how="inner",
            )

    if merged is None or classes is None:
        raise RuntimeError("No 4-class Florida evaluation runs found.")

    for class_name in classes:
        class_prob_cols = [f"prob_{class_name}_fold{idx:02d}" for idx in range(len(runs))]
        merged[f"prob_{class_name}"] = merged[class_prob_cols].mean(axis=1)

    mean_prob_cols = [f"prob_{class_name}" for class_name in classes]
    merged["ensemble_pred_idx"] = merged[mean_prob_cols].to_numpy().argmax(axis=1)
    merged["ensemble_pred"] = merged["ensemble_pred_idx"].map(dict(enumerate(classes)))
    merged["ensemble_correct"] = merged["ensemble_pred"] == merged["true_label"]
    merged["top1_confidence"] = merged[mean_prob_cols].max(axis=1)

    sorted_probs = merged[mean_prob_cols].apply(lambda row: sorted(row.tolist(), reverse=True), axis=1)
    merged["top1_top2_margin"] = sorted_probs.apply(lambda vals: vals[0] - vals[1] if len(vals) > 1 else vals[0])
    return merged


def copy_with_tci(pred_df: pd.DataFrame, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    counts: dict[str, dict[str, int]] = {
        "basarili_tahminler": defaultdict(int),
        "basarisiz_tahminler": defaultdict(int),
    }

    for row in pred_df.itertuples(index=False):
        status_dir = "basarili_tahminler" if bool(row.ensemble_correct) else "basarisiz_tahminler"
        class_dir = str(row.true_label)
        target_dir = output_root / status_dir / class_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        sample_path = Path(row.sample_path)
        if not sample_path.exists():
            raise FileNotFoundError(f"Sample patch not found: {sample_path}")
        sample_target = target_dir / sample_path.name
        shutil.copy2(sample_path, sample_target)

        copied_tci_path = None
        tci_path_raw = row.tci_path
        if isinstance(tci_path_raw, str) and tci_path_raw.strip():
            tci_path = Path(tci_path_raw)
            if tci_path.exists():
                tci_target = target_dir / tci_path.name
                shutil.copy2(tci_path, tci_target)
                copied_tci_path = str(tci_target)

        counts[status_dir][class_dir] += 1
        manifest_rows.append(
            {
                "status_dir": status_dir,
                "true_label": row.true_label,
                "pred_label": row.ensemble_pred,
                "correct": bool(row.ensemble_correct),
                "sample_path": str(sample_target),
                "sample_name": sample_path.name,
                "tci_path": copied_tci_path,
                "source_sample_path": row.sample_path,
                "source_tci_path": row.tci_path,
                "top1_confidence": float(row.top1_confidence),
                "top1_top2_margin": float(row.top1_top2_margin),
            }
        )

    manifest_df = pd.DataFrame(manifest_rows).sort_values(
        ["status_dir", "true_label", "sample_name"], ascending=[True, True, True]
    )
    manifest_df.to_csv(output_root / "ensemble_manifest.csv", index=False)

    summary = {
        "source_eval": "4-class AWS ensemble over latest fold evaluations",
        "total_multiband_patches": int(len(pred_df)),
        "successful_patch_count": int(pred_df["ensemble_correct"].sum()),
        "failed_patch_count": int((~pred_df["ensemble_correct"]).sum()),
        "folders": {
            "basarili_tahminler": {key: int(val) for key, val in sorted(counts["basarili_tahminler"].items())},
            "basarisiz_tahminler": {key: int(val) for key, val in sorted(counts["basarisiz_tahminler"].items())},
        },
    }
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    eval_root = repo_root / "ais-sentinel2-shiptype-classification-main" / "results_aws_florida_eval_runs"
    output_root = (
        repo_root
        / "noaa_accessais_sentinel2_testset"
        / "data"
        / "patches"
        / "florida_4class_ensemble_split"
    )

    runs = find_latest_runs(eval_root)
    pred_df = load_ensemble_predictions(runs)
    summary = copy_with_tci(pred_df, output_root)

    print(f"Latest 4-class fold runs used: {len(runs)}")
    for run in runs:
        print(run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Output root: {output_root}")


if __name__ == "__main__":
    main()
