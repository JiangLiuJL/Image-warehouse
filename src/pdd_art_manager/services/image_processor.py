from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from pdd_art_manager.models import ImageInfo, SizeSpec


CM_PER_INCH = 2.54


def target_pixels(size: SizeSpec) -> tuple[int, int]:
    width_px = round(size.width_cm / CM_PER_INCH * size.dpi)
    height_px = round(size.height_cm / CM_PER_INCH * size.dpi)
    return width_px, height_px


def read_image_info(path: Path) -> ImageInfo:
    with Image.open(path) as image:
        dpi = image.info.get("dpi", (None, None))
        return ImageInfo(
            path=path,
            width_px=image.width,
            height_px=image.height,
            dpi_x=dpi[0],
            dpi_y=dpi[1],
            file_format=image.format or path.suffix.lstrip(".").upper(),
        )


def generate_sized_image(source: Path, destination: Path, size: SizeSpec) -> tuple[int, int]:
    width_px, height_px = target_pixels(size)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        converted = image.convert("RGB")
        resized = ImageOps.fit(
            converted,
            (width_px, height_px),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        resized.save(destination, quality=95, dpi=(size.dpi, size.dpi))

    return width_px, height_px

