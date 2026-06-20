from pdd_art_manager.models import SizeSpec
from pdd_art_manager.services.code_generator import make_base_code, make_full_code, next_sequence


def test_make_base_code_uses_four_hex_digits() -> None:
    assert make_base_code("sg", 175) == "SG-00AF"


def test_make_full_code_appends_size() -> None:
    assert make_full_code("SG-00AF", SizeSpec(20, 30, 150)) == "SG-00AF-20-30"


def test_next_sequence_skips_used_codes() -> None:
    assert next_sequence({"SG-0001", "SG-0002"}, "SG") == 3

