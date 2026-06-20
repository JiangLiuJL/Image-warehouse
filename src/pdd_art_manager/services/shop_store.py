from __future__ import annotations

import json
from pathlib import Path

from pdd_art_manager.config import SHOPS_FILE, ensure_app_dirs
from pdd_art_manager.models import Shop


def load_shops(path: Path = SHOPS_FILE) -> list[Shop]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Shop(
            name=item["name"],
            short_name=item.get("short_name", item["name"]),
            prefix=item["prefix"],
            original_folder=Path(item["original_folder"]),
            output_folder=Path(item["output_folder"]),
            enabled=item.get("enabled", True),
            remark=item.get("remark", ""),
        )
        for item in data
    ]


def save_shops(shops: list[Shop], path: Path = SHOPS_FILE) -> None:
    ensure_app_dirs()
    payload = [
        {
            "name": shop.name,
            "short_name": shop.short_name,
            "prefix": shop.prefix,
            "original_folder": str(shop.original_folder),
            "output_folder": str(shop.output_folder),
            "enabled": shop.enabled,
            "remark": shop.remark,
        }
        for shop in shops
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

