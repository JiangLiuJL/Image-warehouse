from __future__ import annotations

from pathlib import Path


def build_thumbnail_row_indexes(row_count: int) -> list[int]:
    return list(range(max(0, row_count)))


def next_thumbnail_batch(row_indexes: list[int], start: int, batch_size: int) -> list[int]:
    if batch_size <= 0:
        return []
    return row_indexes[start : start + batch_size]


def build_thumbnail_jobs(rows: list[dict[str, str]]) -> list[tuple[int, Path]]:
    jobs: list[tuple[int, Path]] = []
    for index, row in enumerate(rows):
        output_path = row.get("output_path", "").strip()
        if output_path:
            jobs.append((index, Path(output_path)))
    return jobs
