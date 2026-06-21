from pathlib import Path

from pdd_art_manager.services.index_store import delete_index_rows


def test_delete_index_rows_removes_selected_full_codes(tmp_path: Path) -> None:
    rows = [
        {"full_code": "SG-0001-20-30", "output_path": "a.jpg"},
        {"full_code": "SG-0002-30-45", "output_path": "b.jpg"},
        {"full_code": "SG-0003-40-60", "output_path": "c.jpg"},
    ]

    remaining = delete_index_rows(rows, {"SG-0002-30-45"})

    assert remaining == [
        {"full_code": "SG-0001-20-30", "output_path": "a.jpg"},
        {"full_code": "SG-0003-40-60", "output_path": "c.jpg"},
    ]
