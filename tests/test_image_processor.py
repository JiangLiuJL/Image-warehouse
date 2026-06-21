from pdd_art_manager.models import SizeSpec
from pdd_art_manager.services.image_processor import generate_sized_image, target_pixels
from PIL import Image


def test_target_pixels_for_20_by_30_at_150_dpi() -> None:
    assert target_pixels(SizeSpec(20, 30, 150)) == (1181, 1772)


def test_generate_sized_image_adds_inner_bottom_label_border(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.jpg"
    Image.new("RGB", (800, 1200), (20, 120, 200)).save(source)

    width, height = generate_sized_image(source, output, SizeSpec(20, 30, 150), label="SY-0001-20-30")

    with Image.open(output) as image:
        assert image.size == (width, height)
        assert image.getpixel((width // 2, height - 5)) == (255, 255, 255)
        assert image.getpixel((width // 2, height - 40)) != (255, 255, 255)
