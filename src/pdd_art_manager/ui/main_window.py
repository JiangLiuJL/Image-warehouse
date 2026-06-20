from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pdd_art_manager.config import APP_NAME, DATA_DIR, ensure_app_dirs
from pdd_art_manager.models import ImageIndexRow, Shop, SizeSpec
from pdd_art_manager.services.code_generator import (
    make_base_code,
    make_full_code,
    next_sequence,
    normalize_shop_prefix,
)
from pdd_art_manager.services.image_processor import (
    generate_sized_image,
    read_image_info,
    target_pixels,
)
from pdd_art_manager.services.index_store import (
    append_index_row,
    load_base_codes,
    load_index_rows,
)
from pdd_art_manager.services.shop_store import load_shops, save_shops


DEFAULT_SIZES = [(20, 30), (30, 40), (40, 60)]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dirs()
        self.shops = load_shops()
        self.selected_image: Path | None = None
        self.generated_base_code: str | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(1040, 680)
        self._apply_style()
        self.setCentralWidget(self._build_shell())
        self._refresh_all()

    def _build_shell(self) -> QWidget:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(18, 22, 18, 18)
        side_layout.setSpacing(10)

        brand = QLabel("Image Warehouse")
        brand.setObjectName("Brand")
        caption = QLabel("Decorative art manager")
        caption.setObjectName("Caption")

        self.nav_buttons: list[QPushButton] = []
        nav_items = [
            ("Overview", 0),
            ("Upload", 1),
            ("Shops", 2),
            ("Library", 3),
        ]
        side_layout.addWidget(brand)
        side_layout.addWidget(caption)
        side_layout.addSpacing(18)
        for text, index in nav_items:
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=index: self._set_page(page))
            self.nav_buttons.append(button)
            side_layout.addWidget(button)
        side_layout.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("SideStatus")
        self.status_label.setWordWrap(True)
        side_layout.addWidget(self.status_label)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_overview_page())
        self.pages.addWidget(self._build_upload_page())
        self.pages.addWidget(self._build_shops_page())
        self.pages.addWidget(self._build_library_page())

        layout.addWidget(sidebar)
        layout.addWidget(self.pages)
        self._set_page(0)
        return root

    def _build_overview_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(18)

        layout.addWidget(self._page_title("Overview", "A quiet workspace for shop folders, codes, and print sizes."))

        metrics = QGridLayout()
        metrics.setSpacing(14)
        self.shop_count_label = self._metric("0", "Shops")
        self.image_count_label = self._metric("0", "Generated images")
        self.data_path_label = self._metric(str(DATA_DIR), "Local records")
        metrics.addWidget(self.shop_count_label, 0, 0)
        metrics.addWidget(self.image_count_label, 0, 1)
        metrics.addWidget(self.data_path_label, 0, 2)
        layout.addLayout(metrics)

        quick = self._panel()
        quick_layout = QVBoxLayout(quick)
        quick_layout.addWidget(self._section_title("Next actions"))
        actions = QHBoxLayout()
        upload = QPushButton("Upload image")
        upload.clicked.connect(lambda: self._set_page(1))
        shops = QPushButton("Manage shops")
        shops.clicked.connect(lambda: self._set_page(2))
        library = QPushButton("Open library")
        library.clicked.connect(lambda: self._set_page(3))
        for button in (upload, shops, library):
            button.setMinimumHeight(42)
            actions.addWidget(button)
        quick_layout.addLayout(actions)
        layout.addWidget(quick)
        layout.addStretch()
        return page

    def _build_upload_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("Upload", "Choose a shop, inspect the image, and generate print-ready sizes."))

        body = QHBoxLayout()
        body.setSpacing(16)

        left = self._panel()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self._section_title("Source image"))
        self.preview_label = QLabel("No image selected")
        self.preview_label.setObjectName("Preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(360, 430)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_layout.addWidget(self.preview_label)
        choose = QPushButton("Choose image")
        choose.clicked.connect(self._choose_image)
        left_layout.addWidget(choose)

        right = self._panel()
        form_layout = QVBoxLayout(right)
        form_layout.addWidget(self._section_title("Generate files"))

        form = QFormLayout()
        self.upload_shop_combo = QComboBox()
        self.base_code_input = QLineEdit()
        self.base_code_input.setPlaceholderText("Auto-generated, such as SG-00AF")
        self.image_info_label = QLabel("Select an image to read pixels and DPI.")
        self.image_info_label.setWordWrap(True)

        code_row = QHBoxLayout()
        code_row.addWidget(self.base_code_input)
        code_button = QPushButton("Generate code")
        code_button.clicked.connect(self._generate_code)
        code_row.addWidget(code_button)

        form.addRow("Shop", self.upload_shop_combo)
        form.addRow("Base code", code_row)
        form.addRow("Image info", self.image_info_label)
        form_layout.addLayout(form)

        form_layout.addWidget(self._section_title("Sizes"))
        self.size_checks: list[tuple[QCheckBox, int, int]] = []
        size_grid = QGridLayout()
        for index, (width, height) in enumerate(DEFAULT_SIZES):
            checkbox = QCheckBox(f"{width} x {height} cm")
            checkbox.setChecked(index == 0)
            self.size_checks.append((checkbox, width, height))
            size_grid.addWidget(checkbox, index // 2, index % 2)
        form_layout.addLayout(size_grid)

        custom_row = QHBoxLayout()
        self.custom_size_check = QCheckBox("Custom")
        self.custom_width = QSpinBox()
        self.custom_width.setRange(1, 300)
        self.custom_width.setValue(50)
        self.custom_height = QSpinBox()
        self.custom_height.setRange(1, 300)
        self.custom_height.setValue(70)
        custom_row.addWidget(self.custom_size_check)
        custom_row.addWidget(QLabel("W"))
        custom_row.addWidget(self.custom_width)
        custom_row.addWidget(QLabel("H"))
        custom_row.addWidget(self.custom_height)
        form_layout.addLayout(custom_row)

        dpi_row = QHBoxLayout()
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(150)
        dpi_row.addWidget(QLabel("DPI"))
        dpi_row.addWidget(self.dpi_spin)
        dpi_row.addStretch()
        form_layout.addLayout(dpi_row)

        self.generate_button = QPushButton("Generate selected sizes")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.setMinimumHeight(44)
        self.generate_button.clicked.connect(self._generate_images)
        form_layout.addWidget(self.generate_button)
        form_layout.addStretch()

        body.addWidget(left, 3)
        body.addWidget(right, 2)
        layout.addLayout(body)
        return page

    def _build_shops_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("Shops", "Each shop can keep its own source and generated image folders."))

        panel = self._panel()
        panel_layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.shop_name_input = QLineEdit()
        self.shop_short_input = QLineEdit()
        self.shop_prefix_input = QLineEdit()
        self.shop_prefix_input.setMaxLength(2)
        self.original_folder_input = QLineEdit()
        self.output_folder_input = QLineEdit()

        original_row = self._path_row(self.original_folder_input)
        output_row = self._path_row(self.output_folder_input)

        form.addRow("Shop name", self.shop_name_input)
        form.addRow("Short name", self.shop_short_input)
        form.addRow("Prefix", self.shop_prefix_input)
        form.addRow("Source folder", original_row)
        form.addRow("Output folder", output_row)
        panel_layout.addLayout(form)

        save_button = QPushButton("Save shop")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_shop)
        panel_layout.addWidget(save_button)
        layout.addWidget(panel)

        self.shop_table = QTableWidget(0, 5)
        self.shop_table.setHorizontalHeaderLabels(["Shop", "Prefix", "Source folder", "Output folder", "Enabled"])
        self._prepare_table(self.shop_table)
        layout.addWidget(self.shop_table)
        return page

    def _build_library_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("Library", "Generated image records saved in the local CSV index."))

        toolbar = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_library)
        toolbar.addWidget(refresh)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.library_table = QTableWidget(0, 8)
        self.library_table.setHorizontalHeaderLabels(
            ["Code", "Shop", "Size", "DPI", "Pixels", "Original", "Output", "Created"]
        )
        self._prepare_table(self.library_table)
        layout.addWidget(self.library_table)
        return page

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose image",
            "",
            "Images (*.jpg *.jpeg *.png *.webp)",
        )
        if not path:
            return
        self.selected_image = Path(path)
        info = read_image_info(self.selected_image)
        dpi_text = f"{info.dpi_x:g} x {info.dpi_y:g}" if info.dpi_x and info.dpi_y else "not set"
        self.image_info_label.setText(
            f"{info.width_px} x {info.height_px} px | DPI: {dpi_text} | {info.file_format}"
        )
        pixmap = QPixmap(path)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.status_label.setText(f"Selected {self.selected_image.name}")

    def _generate_code(self) -> None:
        shop = self._selected_shop()
        if shop is None:
            self._warn("Add or select a shop before generating a code.")
            return
        try:
            existing = load_base_codes()
            sequence = next_sequence(existing, shop.prefix)
            self.generated_base_code = make_base_code(shop.prefix, sequence)
            self.base_code_input.setText(self.generated_base_code)
            self.status_label.setText(f"Generated {self.generated_base_code}")
        except ValueError as error:
            self._warn(str(error))

    def _generate_images(self) -> None:
        if self.selected_image is None:
            self._warn("Choose an image first.")
            return
        shop = self._selected_shop()
        if shop is None:
            self._warn("Add or select a shop first.")
            return
        base_code = self.base_code_input.text().strip().upper()
        if not base_code:
            self._generate_code()
            base_code = self.base_code_input.text().strip().upper()
        sizes = self._selected_sizes()
        if not sizes:
            self._warn("Select at least one size.")
            return

        try:
            info = read_image_info(self.selected_image)
            shop.original_folder.mkdir(parents=True, exist_ok=True)
            shop.output_folder.mkdir(parents=True, exist_ok=True)

            original_copy = shop.original_folder / self.selected_image.name
            if self.selected_image.resolve() != original_copy.resolve():
                shutil.copy2(self.selected_image, original_copy)

            created = 0
            for size in sizes:
                full_code = make_full_code(base_code, size)
                output_dir = shop.output_folder / size.code_suffix
                output_path = output_dir / f"{full_code}.jpg"
                output_width, output_height = generate_sized_image(original_copy, output_path, size)
                append_index_row(
                    ImageIndexRow(
                        shop_name=shop.name,
                        shop_prefix=shop.prefix,
                        base_code=base_code,
                        full_code=full_code,
                        original_name=self.selected_image.name,
                        original_path=original_copy,
                        output_path=output_path,
                        width_cm=size.width_cm,
                        height_cm=size.height_cm,
                        dpi=size.dpi,
                        width_px=info.width_px,
                        height_px=info.height_px,
                        output_width_px=output_width,
                        output_height_px=output_height,
                        file_format="JPG",
                        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    )
                )
                created += 1
            self.status_label.setText(f"Generated {created} image file(s).")
            self._refresh_all()
            self._info(f"Generated {created} image file(s).")
        except Exception as error:
            self._warn(f"Failed to generate images: {error}")

    def _save_shop(self) -> None:
        try:
            prefix = normalize_shop_prefix(self.shop_prefix_input.text())
        except ValueError as error:
            self._warn(str(error))
            return
        name = self.shop_name_input.text().strip()
        if not name:
            self._warn("Shop name is required.")
            return
        original_folder = Path(self.original_folder_input.text().strip())
        output_folder = Path(self.output_folder_input.text().strip())
        if not str(original_folder) or not str(output_folder):
            self._warn("Both folders are required.")
            return

        shop = Shop(
            name=name,
            short_name=self.shop_short_input.text().strip() or name,
            prefix=prefix,
            original_folder=original_folder,
            output_folder=output_folder,
        )
        self.shops = [item for item in self.shops if item.prefix != prefix]
        self.shops.append(shop)
        save_shops(self.shops)
        self.shop_name_input.clear()
        self.shop_short_input.clear()
        self.shop_prefix_input.clear()
        self.original_folder_input.clear()
        self.output_folder_input.clear()
        self.status_label.setText(f"Saved shop {shop.name}")
        self._refresh_all()

    def _selected_shop(self) -> Shop | None:
        index = self.upload_shop_combo.currentIndex()
        if index < 0 or index >= len(self.shops):
            return None
        return self.shops[index]

    def _selected_sizes(self) -> list[SizeSpec]:
        dpi = self.dpi_spin.value()
        sizes = [
            SizeSpec(width, height, dpi)
            for checkbox, width, height in self.size_checks
            if checkbox.isChecked()
        ]
        if self.custom_size_check.isChecked():
            sizes.append(SizeSpec(self.custom_width.value(), self.custom_height.value(), dpi))
        return sizes

    def _refresh_all(self) -> None:
        self.shops = load_shops()
        self._refresh_shop_combo()
        self._refresh_shops_table()
        self._refresh_library()
        rows = load_index_rows()
        self.shop_count_label.findChild(QLabel, "MetricValue").setText(str(len(self.shops)))
        self.image_count_label.findChild(QLabel, "MetricValue").setText(str(len(rows)))

    def _refresh_shop_combo(self) -> None:
        self.upload_shop_combo.clear()
        for shop in self.shops:
            self.upload_shop_combo.addItem(f"{shop.name} ({shop.prefix})")

    def _refresh_shops_table(self) -> None:
        self.shop_table.setRowCount(len(self.shops))
        for row, shop in enumerate(self.shops):
            values = [
                shop.name,
                shop.prefix,
                str(shop.original_folder),
                str(shop.output_folder),
                "Yes" if shop.enabled else "No",
            ]
            for column, value in enumerate(values):
                self.shop_table.setItem(row, column, QTableWidgetItem(value))

    def _refresh_library(self) -> None:
        rows = load_index_rows()
        self.library_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("full_code", ""),
                row.get("shop_name", ""),
                f"{row.get('width_cm', '')} x {row.get('height_cm', '')}",
                row.get("dpi", ""),
                f"{row.get('output_width_px', '')} x {row.get('output_height_px', '')}",
                row.get("original_name", ""),
                row.get("output_path", ""),
                row.get("created_at", ""),
            ]
            for column, value in enumerate(values):
                self.library_table.setItem(row_index, column, QTableWidgetItem(value))

    def _set_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def _path_row(self, line_edit: QLineEdit) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("Browse")
        browse.clicked.connect(lambda: self._browse_folder(line_edit))
        layout.addWidget(line_edit)
        layout.addWidget(browse)
        return container

    def _browse_folder(self, line_edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder")
        if folder:
            line_edit.setText(folder)

    def _page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        return page

    def _page_title(self, title: str, subtitle: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        layout.addWidget(heading)
        layout.addWidget(sub)
        return container

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        return panel

    def _metric(self, value: str, label: str) -> QFrame:
        frame = self._panel()
        frame.setMinimumHeight(112)
        layout = QVBoxLayout(frame)
        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")
        value_label.setWordWrap(True)
        text_label = QLabel(label)
        text_label.setObjectName("MetricLabel")
        layout.addWidget(value_label)
        layout.addWidget(text_label)
        return frame

    def _prepare_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Image Warehouse", text)

    def _info(self, text: str) -> None:
        QMessageBox.information(self, "Image Warehouse", text)

    def _apply_style(self) -> None:
        QApplication.instance().setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 14px;
                color: #222222;
                background: #f6f7f4;
            }
            #Sidebar {
                background: #24312f;
            }
            #Brand {
                color: #ffffff;
                font-size: 22px;
                font-weight: 700;
                background: transparent;
            }
            #Caption, #SideStatus {
                color: #c9d3cd;
                background: transparent;
            }
            #NavButton {
                text-align: left;
                padding: 12px 14px;
                border: none;
                border-radius: 7px;
                color: #eaf0eb;
                background: transparent;
            }
            #NavButton:hover {
                background: #31423f;
            }
            #NavButton:checked {
                background: #d8efe5;
                color: #14231f;
                font-weight: 600;
            }
            #Page {
                background: #f6f7f4;
                padding: 24px;
            }
            #PageTitle {
                font-size: 30px;
                font-weight: 700;
                color: #17201e;
            }
            #PageSubtitle {
                color: #63706b;
                font-size: 14px;
            }
            #Panel {
                background: #ffffff;
                border: 1px solid #dde4df;
                border-radius: 8px;
            }
            #SectionTitle {
                font-size: 16px;
                font-weight: 700;
                color: #23302d;
                background: transparent;
            }
            #MetricValue {
                font-size: 24px;
                font-weight: 700;
                color: #25332f;
                background: transparent;
            }
            #MetricLabel {
                color: #67736f;
                background: transparent;
            }
            #Preview {
                border: 1px dashed #b7c2bd;
                border-radius: 8px;
                background: #fbfcfa;
                color: #7b8580;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #cbd6d1;
                border-radius: 7px;
                padding: 9px 14px;
            }
            QPushButton:hover {
                background: #edf4f0;
            }
            #PrimaryButton {
                background: #2f6f5f;
                color: #ffffff;
                border: 1px solid #2f6f5f;
                font-weight: 600;
            }
            #PrimaryButton:hover {
                background: #285f52;
            }
            QLineEdit, QComboBox, QSpinBox, QTextEdit {
                background: #ffffff;
                border: 1px solid #cbd6d1;
                border-radius: 6px;
                padding: 8px;
            }
            QTableWidget {
                background: #ffffff;
                alternate-background-color: #f1f5f2;
                border: 1px solid #dde4df;
                border-radius: 8px;
                gridline-color: #e5ebe7;
            }
            QHeaderView::section {
                background: #e8eee9;
                padding: 9px;
                border: none;
                font-weight: 600;
            }
            """
        )

