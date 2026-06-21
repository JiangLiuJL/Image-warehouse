from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

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


def generate_sized_image(
    source: Path,
    destination: Path,
    size: SizeSpec,
    label: str | None = None,
) -> tuple[int, int]:
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
        if label:
            add_bottom_label_border(resized, label, size.dpi)
        resized.save(destination, quality=95, dpi=(size.dpi, size.dpi))

    return width_px, height_px


def add_bottom_label_border(image: Image.Image, label: str, dpi: int) -> None:
    border_height = max(1, round(0.6 / CM_PER_INCH * dpi))
    border_top = max(0, image.height - border_height)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, border_top, image.width, image.height), fill="white")

    font_size = max(10, round(border_height * 0.45))
    font = load_label_font(font_size)
    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    margin_x = max(6, round(0.15 / CM_PER_INCH * dpi))
    text_x = margin_x
    text_y = border_top + max(0, (border_height - text_height) // 2) - bbox[1]
    if text_x + text_width > image.width:
        text_x = max(0, image.width - text_width - margin_x)
    draw.text((text_x, text_y), label, fill="black", font=font)


def load_label_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
