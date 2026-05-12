from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

import requests

from .config_utils import daterange, ensure_dir


def build_download_jobs(config: dict) -> list[tuple[str, Path]]:
    study_area = config["study_area"]
    download_cfg = config["download"]
    raw_dir = ensure_dir(config["paths"]["raw_dir"])

    start_date = datetime.strptime(study_area["start_date"], "%Y-%m-%d").date()
    end_date = datetime.strptime(study_area["end_date"], "%Y-%m-%d").date()

    jobs = []
    for day in daterange(start_date, end_date):
        day_str = day.isoformat()
        url = download_cfg["url_template"].format(year=day.year, date=day_str)
        out_path = raw_dir / f"ais-{day_str}.csv.zst"
        jobs.append((url, out_path))
    return jobs


def print_download_plan(config: dict) -> None:
    jobs = build_download_jobs(config)
    print(f"study_area={config['study_area']['name']}")
    print(f"date_count={len(jobs)}")
    for url, out_path in jobs[:5]:
        print(f"sample_url={url}")
        print(f"sample_output={out_path}")
    if len(jobs) > 5:
        print("...")
        print(f"last_output={jobs[-1][1]}")


def download_files(config: dict) -> None:
    jobs = build_download_jobs(config)
    download_cfg = config["download"]
    timeout = int(download_cfg.get("timeout_seconds", 180))
    chunk_bytes = int(download_cfg.get("chunk_bytes", 1024 * 1024))
    skip_existing = bool(download_cfg.get("skip_existing", True))

    for url, out_path in jobs:
        temp_path = out_path.with_suffix(out_path.suffix + ".part")

        if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
            if temp_path.exists():
                if temp_path.stat().st_size == out_path.stat().st_size:
                    temp_path.unlink()
                else:
                    temp_path.unlink()
            print(f"skip_existing={out_path.name}")
            continue

        if temp_path.exists():
            temp_path.unlink()

        if out_path.exists() and out_path.stat().st_size == 0:
            print(f"redownload_zero_byte={out_path.name}")

        print(f"downloading={url}")
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(temp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_bytes):
                    if chunk:
                        handle.write(chunk)
        replaced = False
        for _ in range(10):
            try:
                temp_path.replace(out_path)
                replaced = True
                break
            except PermissionError:
                time.sleep(2)
                if out_path.exists() and temp_path.exists():
                    if out_path.stat().st_size == temp_path.stat().st_size:
                        temp_path.unlink()
                        replaced = True
                        break
        if not replaced:
            raise PermissionError(f"Could not finalize download for {out_path.name}")
        print(f"saved={out_path}")
