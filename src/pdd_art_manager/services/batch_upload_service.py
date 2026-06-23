from __future__ import annotations

from pathlib import Path

from pdd_art_manager.services.code_generator import make_base_code, next_sequence


def assign_batch_base_codes(
    image_paths: list[Path],
    existing_base_codes: set[str],
    shop_prefix: str,
) -> list[tuple[str, str]]:
    assigned: list[tuple[str, str]] = []
    used_codes = set(existing_base_codes)
    for path in image_paths:
        sequence = next_sequence(used_codes, shop_prefix)
        base_code = make_base_code(shop_prefix, sequence)
        used_codes.add(base_code)
        assigned.append((path.name, base_code))
    return assigned
