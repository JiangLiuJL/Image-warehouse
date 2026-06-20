from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from pdd_art_manager.config import IMAGE_INDEX_FILE, ensure_app_dirs
from pdd_art_manager.models import ImageIndexRow


FIELDNAMES = [
    "shop_name",
    "shop_prefix",
    "base_code",
    "full_code",
    "original_name",
    "original_path",
    "output_path",
    "width_cm",
    "height_cm",
    "dpi",
    "width_px",
    "height_px",
    "output_width_px",
    "output_height_px",
    "file_format",
    "created_at",
    "remark",
]


def append_index_row(row: ImageIndexRow, path: Path = IMAGE_INDEX_FILE) -> None:
    ensure_app_dirs()
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({key: str(value) for key, value in asdict(row).items()})


def load_base_codes(path: Path = IMAGE_INDEX_FILE) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return {row["base_code"] for row in reader if row.get("base_code")}

