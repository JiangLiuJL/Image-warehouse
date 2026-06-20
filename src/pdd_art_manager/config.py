from __future__ import annotations

from pathlib import Path


APP_NAME = "装饰画图片管理"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
BACKUP_DIR = PROJECT_ROOT / "backups"

SHOPS_FILE = DATA_DIR / "shops.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
IMAGE_INDEX_FILE = DATA_DIR / "image_index.csv"


def ensure_app_dirs() -> None:
    for path in (DATA_DIR, LOG_DIR, BACKUP_DIR):
        path.mkdir(parents=True, exist_ok=True)

