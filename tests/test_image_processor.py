from pdd_art_manager.models import SizeSpec
from pdd_art_manager.services.image_processor import target_pixels


def test_target_pixels_for_20_by_30_at_150_dpi() -> None:
    assert target_pixels(SizeSpec(20, 30, 150)) == (1181, 1772)

