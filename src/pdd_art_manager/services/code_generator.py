from __future__ import annotations

import re

from pdd_art_manager.models import SizeSpec


BASE_CODE_RE = re.compile(r"^[A-Z]{2}-[0-9A-F]{4}$")
FULL_CODE_RE = re.compile(r"^[A-Z]{2}-[0-9A-F]{4}-\d{1,3}-\d{1,3}$")


def make_base_code(shop_prefix: str, sequence: int) -> str:
    if sequence < 0 or sequence > 0xFFFF:
        raise ValueError("sequence must be between 0 and FFFF")
    prefix = normalize_shop_prefix(shop_prefix)
    return f"{prefix}-{sequence:04X}"


def make_full_code(base_code: str, size: SizeSpec) -> str:
    if not BASE_CODE_RE.match(base_code):
        raise ValueError(f"invalid base code: {base_code}")
    return f"{base_code}-{size.code_suffix}"


def normalize_shop_prefix(value: str) -> str:
    prefix = value.strip().upper()
    if not re.match(r"^[A-Z]{2}$", prefix):
        raise ValueError("shop prefix must be two uppercase letters, such as SG")
    return prefix


def next_sequence(existing_base_codes: set[str], shop_prefix: str) -> int:
    prefix = normalize_shop_prefix(shop_prefix)
    used = {
        int(code.split("-")[1], 16)
        for code in existing_base_codes
        if code.startswith(f"{prefix}-") and BASE_CODE_RE.match(code)
    }
    for sequence in range(1, 0x10000):
        if sequence not in used:
            return sequence
    raise RuntimeError(f"no available code left for shop prefix {prefix}")

