from pathlib import Path

from PIL import Image


def test_source_png_can_be_saved_as_jpg_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "copy.jpg"
    Image.new("RGBA", (100, 100), (200, 100, 50, 255)).save(source)

    with Image.open(source) as image:
        image.convert("RGB").save(output, format="JPEG", quality=95)

    assert output.exists()
    assert output.suffix.lower() == ".jpg"
