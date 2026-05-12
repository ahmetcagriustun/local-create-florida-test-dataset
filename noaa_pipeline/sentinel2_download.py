from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg2
import requests

from .config_utils import ensure_dir


TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ZIPPER_URL_TEMPLATE = "https://zipper.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"


def _connect(pg_cfg: dict):
    return psycopg2.connect(
        host=pg_cfg["host"],
        port=pg_cfg.get("port", 5432),
        dbname=pg_cfg["dbname"],
        user=pg_cfg["user"],
        password=pg_cfg["password"],
    )


def get_cdse_token(username: str, password: str) -> tuple[str, float]:
    payload = {
        "client_id": "cdse-public",
        "grant_type": "password",
        "username": username,
        "password": password,
    }
    response = requests.post(TOKEN_URL, data=payload, timeout=60)
    response.raise_for_status()
    return response.json()["access_token"], time.time()


def _token_is_fresh(token_time: float, max_age_seconds: int = 600) -> bool:
    return (time.time() - token_time) < (max_age_seconds - 60)


def fetch_selected_products(config: dict) -> list[tuple[str, str]]:
    pg_cfg = config["postgres"]
    download_cfg = config["sentinel2_download"]
    selected_table = download_cfg["selected_table"]

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT product_id, name
                FROM {selected_table}
                WHERE product_id IS NOT NULL
                  AND name IS NOT NULL
                ORDER BY sensing_start
                """
            )
            return cur.fetchall()


def estimate_selected_download_gb(config: dict) -> tuple[int, float]:
    pg_cfg = config["postgres"]
    download_cfg = config["sentinel2_download"]
    selected_table = download_cfg["selected_table"]

    with _connect(pg_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*),
                       COALESCE(SUM(content_length_bytes), 0) / 1024.0 / 1024.0 / 1024.0
                FROM {selected_table}
                """
            )
            count, total_gb = cur.fetchone()
    return int(count), float(total_gb)


def download_selected_products(config: dict) -> None:
    cop_cfg = config["copernicus"]
    download_cfg = config["sentinel2_download"]
    out_dir = ensure_dir(download_cfg["output_dir"])
    timeout = int(download_cfg.get("timeout_seconds", 180))
    chunk_bytes = int(download_cfg.get("chunk_bytes", 1024 * 1024))
    skip_existing = bool(download_cfg.get("skip_existing", True))

    products = fetch_selected_products(config)
    access_token, token_time = get_cdse_token(cop_cfg["username"], cop_cfg["password"])
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {access_token}"})

    for index, (product_id, product_name) in enumerate(products, start=1):
        zip_name = f"{product_name}.zip"
        final_path = out_dir / zip_name
        temp_path = Path(str(final_path) + ".part")

        if temp_path.exists():
            temp_path.unlink()

        if skip_existing and final_path.exists() and final_path.stat().st_size > 0:
            print(f"skip_existing={zip_name}")
            continue

        if final_path.exists() and final_path.stat().st_size == 0:
            print(f"redownload_zero_byte={zip_name}")

        if not _token_is_fresh(token_time):
            access_token, token_time = get_cdse_token(cop_cfg["username"], cop_cfg["password"])
            session.headers.update({"Authorization": f"Bearer {access_token}"})
            print("token_renewed=true")

        url = ZIPPER_URL_TEMPLATE.format(product_id=product_id)
        print(f"download_start={index}/{len(products)} name={zip_name}")
        with session.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(temp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_bytes):
                    if chunk:
                        handle.write(chunk)

        temp_path.replace(final_path)
        print(f"download_done={zip_name} size_bytes={final_path.stat().st_size}")
