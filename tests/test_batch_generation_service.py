from pathlib import Path

from pdd_art_manager.models import SizeSpec
from pdd_art_manager.services.batch_generation_service import build_batch_generation_tasks


def test_build_batch_generation_tasks_preserves_image_and_size_order() -> None:
    tasks = build_batch_generation_tasks(
        batch_base_codes=[(Path("a.jpg"), "SY-0001"), (Path("b.jpg"), "SY-0002")],
        sizes=[SizeSpec(20, 30, 150), SizeSpec(30, 45, 150)],
    )

    assert tasks == [
        (Path("a.jpg"), "SY-0001", SizeSpec(20, 30, 150)),
        (Path("a.jpg"), "SY-0001", SizeSpec(30, 45, 150)),
        (Path("b.jpg"), "SY-0002", SizeSpec(20, 30, 150)),
        (Path("b.jpg"), "SY-0002", SizeSpec(30, 45, 150)),
    ]
