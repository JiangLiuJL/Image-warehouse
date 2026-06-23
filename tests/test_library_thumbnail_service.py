from pathlib import Path

from pdd_art_manager.services.library_thumbnail_service import (
    build_thumbnail_jobs,
    build_thumbnail_row_indexes,
    next_thumbnail_batch,
)


def test_build_thumbnail_row_indexes_matches_table_rows() -> None:
    assert build_thumbnail_row_indexes(4) == [0, 1, 2, 3]


def test_next_thumbnail_batch_returns_only_requested_slice() -> None:
    row_indexes = [0, 1, 2, 3, 4]

    assert next_thumbnail_batch(row_indexes, start=1, batch_size=2) == [1, 2]


def test_build_thumbnail_jobs_skips_empty_paths() -> None:
    jobs = build_thumbnail_jobs(
        [
            {"output_path": "a.jpg"},
            {"output_path": ""},
            {"output_path": "b.jpg"},
        ]
    )

    assert jobs == [
        (0, Path("a.jpg")),
        (2, Path("b.jpg")),
    ]
