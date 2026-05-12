from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path


def copy_tree_flat_by_class(src_root: Path, dst_root: Path, counts: Counter[str]) -> None:
    if not src_root.exists():
        raise FileNotFoundError(f"Source folder not found: {src_root}")

    for class_dir in sorted(p for p in src_root.iterdir() if p.is_dir()):
        dst_class = dst_root / class_dir.name
        dst_class.mkdir(parents=True, exist_ok=True)
        for src_file in sorted(p for p in class_dir.iterdir() if p.is_file()):
            dst_file = dst_class / src_file.name
            shutil.copy2(src_file, dst_file)
            counts[class_dir.name] += 1


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_multiband = repo_root / "data" / "patches" / "florida_6class_by_type"
    src_tci = repo_root / "data" / "patches" / "florida_6class_tci"
    out_root = repo_root / "data" / "patches" / "florida_6class_manual_review_all"

    out_root.mkdir(parents=True, exist_ok=True)

    multiband_counts: Counter[str] = Counter()
    tci_counts: Counter[str] = Counter()

    copy_tree_flat_by_class(src_multiband, out_root, multiband_counts)
    copy_tree_flat_by_class(src_tci, out_root, tci_counts)

    summary = {
        "source_multiband": str(src_multiband),
        "source_tci": str(src_tci),
        "output_root": str(out_root),
        "multiband_counts": dict(multiband_counts),
        "tci_counts": dict(tci_counts),
        "total_multiband": int(sum(multiband_counts.values())),
        "total_tci": int(sum(tci_counts.values())),
        "total_output_files": int(sum(multiband_counts.values()) + sum(tci_counts.values())),
    }

    summary_path = repo_root / "outputs" / "florida_6class_manual_review_all_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
