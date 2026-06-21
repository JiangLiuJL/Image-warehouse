from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook


@dataclass(slots=True)
class PrintJobResult:
    output_folder: Path
    completed_codes: int
    total_copies: int
    missing_codes: list[tuple[str, int]]


def load_order_rows(path: Path) -> list[list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        for encoding in ("utf-8-sig", "gbk", "gb18030"):
            try:
                with path.open("r", newline="", encoding=encoding) as file:
                    return [list(row) for row in csv.reader(file)]
            except UnicodeDecodeError:
                continue
        raise ValueError("订单 CSV 编码无法识别，请另存为 UTF-8 或 Excel 后重试。")
    if suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            return [
                ["" if value is None else str(value) for value in row]
                for row in sheet.iter_rows(values_only=True)
            ]
        finally:
            workbook.close()
    raise ValueError("当前只支持导入 CSV 订单文件。")


def parse_order_rows(rows: list[list[str]]) -> dict[str, int]:
    order_counts: dict[str, int] = {}
    for row in rows:
        if len(row) < 4:
            continue
        quantity_text = str(row[2]).strip()
        full_code = str(row[3]).strip().upper()
        if not full_code:
            continue
        try:
            quantity = int(float(quantity_text))
        except ValueError:
            continue
        if quantity <= 0:
            continue
        order_counts[full_code] = order_counts.get(full_code, 0) + quantity
    return order_counts


def build_print_job(
    order_counts: dict[str, int],
    index_rows: list[dict[str, str]],
    output_root: Path,
    folder_name: str,
) -> PrintJobResult:
    target_root = output_root / folder_name
    target_root.mkdir(parents=True, exist_ok=True)

    index_by_code = {
        row.get("full_code", "").strip().upper(): row
        for row in index_rows
        if row.get("full_code")
    }

    completed_codes = 0
    total_copies = 0
    missing_codes: list[tuple[str, int]] = []

    for full_code, quantity in order_counts.items():
        row = index_by_code.get(full_code)
        if row is None:
            missing_codes.append((full_code, quantity))
            continue

        source_path = Path(row.get("output_path", ""))
        if not source_path.exists():
            missing_codes.append((full_code, quantity))
            continue

        size_folder = f"{row.get('width_cm', '').strip()}-{row.get('height_cm', '').strip()}"
        quantity_folder = f"各{quantity}"
        destination_dir = target_root / size_folder / quantity_folder
        destination_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_dir / source_path.name)
        completed_codes += 1
        total_copies += quantity

    if missing_codes:
        report_lines = [f"{code} x {quantity}" for code, quantity in missing_codes]
        (target_root / "未匹配编码.txt").write_text("\n".join(report_lines), encoding="utf-8")

    return PrintJobResult(
        output_folder=target_root,
        completed_codes=completed_codes,
        total_copies=total_copies,
        missing_codes=missing_codes,
    )
