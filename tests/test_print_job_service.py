from pathlib import Path

from openpyxl import Workbook

from pdd_art_manager.services.print_job_service import (
    build_print_job,
    detect_default_columns,
    load_order_rows,
    parse_order_rows,
    parse_order_rows_with_remarks,
    summarize_order_counts,
)


def test_parse_order_rows_merges_quantities_by_full_code() -> None:
    rows = [
        ["订单1", "A", "2", "SG-0001-20-30"],
        ["订单2", "B", "3", "SG-0001-20-30"],
        ["订单3", "C", "1", "SG-0002-30-40"],
    ]

    result = parse_order_rows(rows)

    assert result.order_counts == {
        "SG-0001-20-30": 5,
        "SG-0002-30-40": 1,
    }
    assert result.remark_ignored_codes == []


def test_build_print_job_copies_images_into_size_and_quantity_folders(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    source_root.mkdir()
    output_root.mkdir()

    image_1 = source_root / "SG-0001-20-30.jpg"
    image_2 = source_root / "SG-0002-30-40.jpg"
    image_1.write_bytes(b"image-1")
    image_2.write_bytes(b"image-2")

    rows = [
        {
            "full_code": "SG-0001-20-30",
            "output_path": str(image_1),
            "width_cm": "20",
            "height_cm": "30",
        },
        {
            "full_code": "SG-0002-30-40",
            "output_path": str(image_2),
            "width_cm": "30",
            "height_cm": "40",
        },
    ]

    result = build_print_job(
        order_counts={
            "SG-0001-20-30": 3,
            "SG-0002-30-40": 1,
        },
        index_rows=rows,
        output_root=output_root,
        folder_name="今天打印",
    )

    target_root = output_root / "今天打印"
    assert (target_root / "20-30" / "各3" / "SG-0001-20-30.jpg").read_bytes() == b"image-1"
    assert (target_root / "30-40" / "各1" / "SG-0002-30-40.jpg").read_bytes() == b"image-2"
    assert result.completed_codes == 2
    assert result.missing_codes == []


def test_build_print_job_writes_missing_code_report(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()

    result = build_print_job(
        order_counts={"SG-9999-20-30": 2},
        index_rows=[],
        output_root=output_root,
        folder_name="缺图测试",
    )

    report_path = output_root / "缺图测试" / "未匹配编码.txt"
    assert report_path.exists()
    assert "SG-9999-20-30 x 2" in report_path.read_text(encoding="utf-8")
    assert result.completed_codes == 0
    assert result.missing_codes == [("SG-9999-20-30", 2)]


def test_build_print_job_can_force_codes_into_missing_report(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    source_root.mkdir()
    output_root.mkdir()

    image_1 = source_root / "SG-0001-20-30.jpg"
    image_1.write_bytes(b"image-1")

    rows = [
        {
            "full_code": "SG-0001-20-30",
            "output_path": str(image_1),
            "width_cm": "20",
            "height_cm": "30",
        }
    ]

    result = build_print_job(
        order_counts={"SG-0001-20-30": 2},
        index_rows=rows,
        output_root=output_root,
        folder_name="备注忽略",
        forced_missing_codes=[("SG-0001-20-30", 2)],
    )

    assert not (output_root / "备注忽略" / "20-30" / "各2" / "SG-0001-20-30.jpg").exists()
    assert ("SG-0001-20-30", 2) in result.missing_codes


def test_load_order_rows_supports_xlsx(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["订单号", "买家", "数量", "图片编码"])
    sheet.append(["1001", "张三", 2, "SG-0001-20-30"])

    path = tmp_path / "orders.xlsx"
    workbook.save(path)

    rows = load_order_rows(path)

    assert rows[1][2] == "2"
    assert rows[1][3] == "SG-0001-20-30"


def test_load_order_rows_supports_gbk_csv(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    content = "订单号,买家,数量,图片编码\n1001,张三,2,SG-0001-20-30\n"
    path.write_bytes(content.encode("gbk"))

    rows = load_order_rows(path)

    assert rows[1][1] == "张三"
    assert rows[1][3] == "SG-0001-20-30"


def test_detect_default_columns_prefers_header_names() -> None:
    rows = [
        ["商品", "订单号", "商品数量(件)", "商家编码-规格维度"],
        ["A", "1001", "2", "SG-0001-20-30"],
    ]

    quantity_index, code_index = detect_default_columns(rows)

    assert quantity_index == 2
    assert code_index == 3


def test_parse_order_rows_supports_selected_columns() -> None:
    rows = [
        ["商品", "编码", "备注", "数量"],
        ["海报1", "SG-0001-20-30", "", "2"],
        ["海报2", "SG-0001-20-30", "", "1"],
    ]

    result = parse_order_rows(rows, quantity_column=3, code_column=1, skip_header=True)

    assert result.order_counts == {"SG-0001-20-30": 3}
    assert result.remark_ignored_codes == []


def test_parse_order_rows_ignores_codes_when_remark_columns_have_values() -> None:
    rows = [
        ["商品", "编码", "备注1", "数量", "备注2", "备注3"],
        ["海报1", "SG-0001-20-30", "", "2", "", ""],
        ["海报2", "SG-0002-30-40", "", "1", "改地址", ""],
        ["海报3", "SG-0003-40-60", "", "3", "", "赠品"],
    ]

    parsed = parse_order_rows_with_remarks(
        rows,
        quantity_column=3,
        code_column=1,
        skip_header=True,
        remark_columns=[4, 5],
    )

    assert parsed.order_counts == {"SG-0001-20-30": 2}
    assert parsed.remark_ignored_codes == [
        ("SG-0002-30-40", 1),
        ("SG-0003-40-60", 3),
    ]


def test_summarize_order_counts_returns_sorted_preview() -> None:
    summary = summarize_order_counts(
        {
            "SG-0002-30-40": 1,
            "SG-0001-20-30": 3,
        }
    )

    assert summary.total_codes == 2
    assert summary.total_copies == 4
    assert summary.preview_rows == [
        ("SG-0001-20-30", 3),
        ("SG-0002-30-40", 1),
    ]
