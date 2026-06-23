from __future__ import annotations

import sys
from pathlib import Path


APP_NAME = "装饰画图片管理"

def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = get_project_root()

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
BACKUP_DIR = PROJECT_ROOT / "backups"

SHOPS_FILE = DATA_DIR / "shops.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
IMAGE_INDEX_FILE = DATA_DIR / "image_index.csv"


def ensure_app_dirs() -> None:
    for path in (DATA_DIR, LOG_DIR, BACKUP_DIR):
        path.mkdir(parents=True, exist_ok=True)
