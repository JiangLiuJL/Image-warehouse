from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Shop:
    name: str
    short_name: str
    prefix: str
    original_folder: Path
    output_folder: Path
    enabled: bool = True
    remark: str = ""


@dataclass(slots=True)
class SizeSpec:
    width_cm: int
    height_cm: int
    dpi: int

    @property
    def code_suffix(self) -> str:
        return f"{self.width_cm}-{self.height_cm}"


@dataclass(slots=True)
class ImageInfo:
    path: Path
    width_px: int
    height_px: int
    dpi_x: float | None
    dpi_y: float | None
    file_format: str


@dataclass(slots=True)
class ImageIndexRow:
    shop_name: str
    shop_prefix: str
    base_code: str
    full_code: str
    original_name: str
    original_path: Path
    output_path: Path
    width_cm: int
    height_cm: int
    dpi: int
    width_px: int
    height_px: int
    output_width_px: int
    output_height_px: int
    file_format: str
    created_at: str
    remark: str = ""

