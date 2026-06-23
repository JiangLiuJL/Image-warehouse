from __future__ import annotations

from pathlib import Path

from pdd_art_manager.models import SizeSpec


def build_batch_generation_tasks(
    batch_base_codes: list[tuple[Path, str]],
    sizes: list[SizeSpec],
) -> list[tuple[Path, str, SizeSpec]]:
    tasks: list[tuple[Path, str, SizeSpec]] = []
    for image_path, base_code in batch_base_codes:
        for size in sizes:
            tasks.append((image_path, base_code, size))
    return tasks
