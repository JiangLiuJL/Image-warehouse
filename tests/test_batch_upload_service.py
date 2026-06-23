from pathlib import Path

from pdd_art_manager.services.batch_upload_service import assign_batch_base_codes


def test_assign_batch_base_codes_uses_consecutive_sequences() -> None:
    image_paths = [
        Path("a.jpg"),
        Path("b.jpg"),
        Path("c.jpg"),
    ]

    result = assign_batch_base_codes(
        image_paths=image_paths,
        existing_base_codes={"SY-0001", "SY-0002"},
        shop_prefix="SY",
    )

    assert result == [
        ("a.jpg", "SY-0003"),
        ("b.jpg", "SY-0004"),
        ("c.jpg", "SY-0005"),
    ]
