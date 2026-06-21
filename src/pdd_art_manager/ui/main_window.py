from __future__ import annotations

import shutil
import sys
import os
import time
from io import BytesIO
from ctypes import c_uint, c_void_p, create_unicode_buffer, windll
from ctypes.wintypes import MAX_PATH
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QIntValidator, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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
from pdd_art_manager.services.image_processor import generate_sized_image, read_image_info
from pdd_art_manager.services.index_store import (
    delete_index_rows,
    append_index_row,
    load_base_codes,
    load_index_rows,
    save_index_rows,
)
from pdd_art_manager.services.print_job_service import (
    build_print_job,
    detect_default_columns,
    load_order_rows,
    parse_order_rows,
    parse_order_rows_with_remarks,
    summarize_order_counts,
)
from pdd_art_manager.services.shop_store import load_shops, save_shops
from PIL import Image, ImageOps


DEFAULT_SIZES = [(20, 30), (30, 45), (40, 60)]


class PasteImagePreview(QLabel):
    paste_requested = Signal()
    image_dropped = Signal(Path)

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._pixmap: QPixmap | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAcceptDrops(True)

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.clear()
        self.setText("")
        self.update()

    def clear_preview(self, text: str) -> None:
        self._pixmap = None
        self.clear()
        self.setText(text)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        self.setFocus()
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._image_path_from_drop(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        path = self._image_path_from_drop(event.mimeData())
        if path is None:
            event.ignore()
            return
        self.image_dropped.emit(path)
        event.acceptProposedAction()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        if self._pixmap is None or self._pixmap.isNull():
            super().paintEvent(event)
            return
        super().paintEvent(event)
        self._render_pixmap()

    def _render_pixmap(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        painter = QPainter(self)
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()

    def _image_path_from_drop(self, mime_data) -> Path | None:  # noqa: ANN001
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and path.exists():
                return path
        return None


class SizeNumberInput(QWidget):
    def __init__(self, value: int, minimum: int, maximum: int) -> None:
        super().__init__()
        self.minimum = minimum
        self.maximum = maximum

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.input = QLineEdit(str(value))
        self.input.setObjectName("SizeNumberInput")
        self.input.setValidator(QIntValidator(minimum, maximum, self))
        self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input.setFixedWidth(48)

        minus_button = QToolButton()
        minus_button.setObjectName("SizeStepButton")
        minus_button.setText("-")
        minus_button.clicked.connect(lambda: self.step_by(-1))

        plus_button = QToolButton()
        plus_button.setObjectName("SizeStepButton")
        plus_button.setText("+")
        plus_button.clicked.connect(lambda: self.step_by(1))

        layout.addWidget(self.input)
        layout.addWidget(minus_button)
        layout.addWidget(plus_button)

    def value(self) -> int:
        text = self.input.text().strip()
        if not text:
            return self.minimum
        return max(self.minimum, min(self.maximum, int(text)))

    def step_by(self, amount: int) -> None:
        self.input.setText(str(max(self.minimum, min(self.maximum, self.value() + amount))))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dirs()
        self._cleanup_preview_cache()
        self.shops = load_shops()
        self.selected_image: Path | None = None
        self.generated_base_code: str | None = None
        self.editing_shop_prefix: str | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)
        self._apply_style()
        self.setCentralWidget(self._build_shell())
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.activated.connect(self._paste_image_from_clipboard)
        QApplication.instance().installEventFilter(self)
        self.library_content.installEventFilter(self)
        self._refresh_all()

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001, N802
        if hasattr(self, "library_loading_overlay") and watched is self.library_content and event.type() == QEvent.Type.Resize:
            self.library_loading_overlay.setGeometry(self.library_content.rect())
        if event.type() == QEvent.Type.DragEnter:
            path = self._image_path_from_drop(event.mimeData())
            if path is not None:
                event.acceptProposedAction()
                return True
        if event.type() == QEvent.Type.Drop:
            path = self._image_path_from_drop(event.mimeData())
            if path is not None:
                self._set_dropped_image(path)
                event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._image_path_from_drop(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        path = self._image_path_from_drop(event.mimeData())
        if path is None:
            event.ignore()
            return
        self._set_dropped_image(path)
        event.acceptProposedAction()

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

        brand = QLabel("图片仓库")
        brand.setObjectName("Brand")
        caption = QLabel("装饰画图片管理")
        caption.setObjectName("Caption")

        self.nav_buttons: list[QPushButton] = []
        nav_items = [("总览", 0), ("上传图片", 1), ("店铺管理", 2), ("图片库", 3), ("打印文件", 4)]
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

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("SideStatus")
        self.status_label.setWordWrap(True)
        side_layout.addWidget(self.status_label)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_overview_page())
        self.pages.addWidget(self._build_upload_page())
        self.pages.addWidget(self._build_shops_page())
        self.pages.addWidget(self._build_library_page())
        self.pages.addWidget(self._build_print_jobs_page())

        layout.addWidget(sidebar)
        layout.addWidget(self.pages)
        self._set_page(0)
        return root

    def _build_overview_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(18)
        layout.addWidget(self._page_title("总览", "管理店铺文件夹、图片编码和打印尺寸。"))

        metrics = QGridLayout()
        metrics.setSpacing(14)
        self.shop_count_label = self._metric("0", "店铺数量")
        self.image_count_label = self._metric("0", "已生成图片")
        self.data_path_label = self._metric(str(DATA_DIR), "本地记录位置")
        metrics.addWidget(self.shop_count_label, 0, 0)
        metrics.addWidget(self.image_count_label, 0, 1)
        metrics.addWidget(self.data_path_label, 0, 2)
        layout.addLayout(metrics)

        quick = self._panel()
        quick_layout = QVBoxLayout(quick)
        quick_layout.addWidget(self._section_title("常用操作"))
        actions = QHBoxLayout()
        upload = QPushButton("上传图片")
        upload.clicked.connect(lambda: self._set_page(1))
        shops = QPushButton("管理店铺")
        shops.clicked.connect(lambda: self._set_page(2))
        library = QPushButton("打开图片库")
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
        layout.addWidget(self._page_title("上传图片", "选择店铺和图片，读取图片信息并生成可打印尺寸。"))

        body = QHBoxLayout()
        body.setSpacing(16)

        left = self._panel()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self._section_title("原图"))
        self.preview_label = PasteImagePreview("未选择图片\n\n点击这里后按 Ctrl+V 可粘贴图片")
        self.preview_label.setObjectName("Preview")
        self.preview_label.setMinimumSize(360, 430)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_label.paste_requested.connect(self._paste_image_from_clipboard)
        self.preview_label.image_dropped.connect(self._set_dropped_image)
        left_layout.addWidget(self.preview_label)
        upload_actions = QHBoxLayout()
        choose = QPushButton("选择图片")
        choose.clicked.connect(self._choose_image)
        paste_button = QPushButton("粘贴图片")
        paste_button.clicked.connect(self._paste_image_from_clipboard)
        self.diagnose_button = QPushButton("诊断粘贴")
        self.diagnose_button.clicked.connect(self._show_clipboard_diagnostics)
        open_diag_button = QPushButton("打开诊断")
        open_diag_button.clicked.connect(self._open_diagnostics_folder)
        upload_actions.addWidget(choose)
        upload_actions.addWidget(paste_button)
        upload_actions.addWidget(self.diagnose_button)
        upload_actions.addWidget(open_diag_button)
        left_layout.addLayout(upload_actions)

        right = self._panel()
        form_layout = QVBoxLayout(right)
        form_layout.addWidget(self._section_title("生成文件"))

        form = QFormLayout()
        self.upload_shop_combo = QComboBox()
        self.base_code_input = QLineEdit()
        self.base_code_input.setPlaceholderText("自动生成，例如 SG-00AF")
        self.image_info_label = QLabel("请选择图片，软件会读取像素和 DPI。")
        self.image_info_label.setWordWrap(True)

        code_row = QHBoxLayout()
        code_row.addWidget(self.base_code_input)
        code_button = QPushButton("生成编码")
        code_button.clicked.connect(self._generate_code)
        code_row.addWidget(code_button)

        form.addRow("店铺", self.upload_shop_combo)
        form.addRow("基础编码", code_row)
        form.addRow("图片信息", self.image_info_label)
        form_layout.addLayout(form)

        size_header = QHBoxLayout()
        size_header.addWidget(self._section_title("尺寸"))
        size_header.addStretch()
        add_size_button = QPushButton("添加尺寸")
        add_size_button.clicked.connect(lambda: self._add_size_row(20, 30, 150))
        size_header.addWidget(add_size_button)
        form_layout.addLayout(size_header)

        self.size_rows: list[tuple[QFrame, SizeNumberInput, SizeNumberInput, SizeNumberInput]] = []
        self.size_list = QWidget()
        self.size_list.setObjectName("SizeList")
        self.size_list_layout = QVBoxLayout(self.size_list)
        self.size_list_layout.setContentsMargins(0, 0, 0, 0)
        self.size_list_layout.setSpacing(8)
        self.size_list_layout.addStretch()

        size_scroll = QScrollArea()
        size_scroll.setObjectName("SizeScroll")
        size_scroll.setWidgetResizable(True)
        size_scroll.setFrameShape(QFrame.Shape.NoFrame)
        size_scroll.setMinimumHeight(190)
        size_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        size_scroll.setWidget(self.size_list)
        form_layout.addWidget(size_scroll, 1)
        for width, height in DEFAULT_SIZES:
            self._add_size_row(width, height, 150)

        self.generate_button = QPushButton("生成所选尺寸")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.setMinimumHeight(44)
        self.generate_button.clicked.connect(self._generate_images)
        form_layout.addWidget(self.generate_button)

        body.addWidget(left, 3)
        body.addWidget(right, 2)
        layout.addLayout(body)
        return page

    def _build_shops_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("店铺管理", "每个店铺可以设置独立的原图文件夹和成品图文件夹。"))

        panel = self._panel()
        panel_layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.shop_name_input = QLineEdit()
        self.shop_short_input = QLineEdit()
        self.shop_prefix_input = QLineEdit()
        self.shop_prefix_input.setMaxLength(2)
        self.original_folder_input = QLineEdit()
        self.output_folder_input = QLineEdit()

        form.addRow("店铺名称", self.shop_name_input)
        form.addRow("店铺简称", self.shop_short_input)
        form.addRow("店铺前缀", self.shop_prefix_input)
        form.addRow("原图文件夹", self._path_row(self.original_folder_input))
        form.addRow("成品图文件夹", self._path_row(self.output_folder_input))
        panel_layout.addLayout(form)

        save_button = QPushButton("保存店铺")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_shop)
        panel_layout.addWidget(save_button)
        layout.addWidget(panel)

        self.shop_table = QTableWidget(0, 5)
        self.shop_table.setHorizontalHeaderLabels(["店铺", "前缀", "原图文件夹", "成品图文件夹", "启用"])
        self._prepare_table(self.shop_table)
        layout.addWidget(self.shop_table)
        return page

    def _build_shops_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("店铺管理", "每个店铺都可以单独设置原图文件夹和成品图文件夹。"))

        panel = self._panel()
        panel_layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.shop_name_input = QLineEdit()
        self.shop_short_input = QLineEdit()
        self.shop_prefix_input = QLineEdit()
        self.shop_prefix_input.setMaxLength(2)
        self.original_folder_input = QLineEdit()
        self.output_folder_input = QLineEdit()

        form.addRow("店铺名称", self.shop_name_input)
        form.addRow("店铺简称", self.shop_short_input)
        form.addRow("店铺前缀", self.shop_prefix_input)
        form.addRow("原图文件夹", self._path_row(self.original_folder_input))
        form.addRow("成品图文件夹", self._path_row(self.output_folder_input))
        panel_layout.addLayout(form)

        save_button = QPushButton("保存店铺")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_shop)
        self.cancel_shop_edit_button = QPushButton("取消编辑")
        self.cancel_shop_edit_button.clicked.connect(self._clear_shop_form)
        self.migrate_shop_button = QPushButton("迁移图片库")
        self.migrate_shop_button.clicked.connect(self._migrate_shop_library)

        button_row = QHBoxLayout()
        button_row.addWidget(save_button)
        button_row.addWidget(self.cancel_shop_edit_button)
        button_row.addWidget(self.migrate_shop_button)
        panel_layout.addLayout(button_row)
        layout.addWidget(panel)

        self.shop_table = QTableWidget(0, 5)
        self.shop_table.setHorizontalHeaderLabels(["店铺", "前缀", "原图文件夹", "成品图文件夹", "启用"])
        self._prepare_table(self.shop_table)
        self.shop_table.itemSelectionChanged.connect(self._on_shop_selection_changed)
        layout.addWidget(self.shop_table)
        return page

    def _build_library_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("图片库", "这里显示保存在本地 CSV 索引中的图片生成记录。"))

        self.library_content = QWidget()
        content_layout = QVBoxLayout(self.library_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        toolbar = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_library)
        toolbar.addWidget(refresh)
        search = QPushButton("搜索")
        search.clicked.connect(self._refresh_library)
        toolbar.addWidget(search)
        delete_record = QPushButton("删除所选")
        delete_record.clicked.connect(self._delete_selected_library_rows)
        toolbar.addWidget(delete_record)
        clear_filters = QPushButton("清空筛选")
        clear_filters.clicked.connect(self._clear_library_filters)
        toolbar.addWidget(clear_filters)
        toolbar.addStretch()
        content_layout.addLayout(toolbar)

        filter_panel = self._panel()
        filter_layout = QGridLayout(filter_panel)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setHorizontalSpacing(8)
        filter_layout.setVerticalSpacing(6)
        self.library_filters: dict[str, QLineEdit] = {}
        filter_fields = [
            ("full_code", "编码"),
            ("shop_name", "店铺"),
            ("size", "尺寸"),
            ("dpi", "DPI"),
            ("pixels", "像素"),
            ("original_name", "原图"),
            ("output_path", "成品图"),
            ("created_at", "生成时间"),
        ]
        for index, (key, label) in enumerate(filter_fields):
            input_box = QLineEdit()
            input_box.setPlaceholderText(label)
            input_box.returnPressed.connect(self._refresh_library)
            self.library_filters[key] = input_box
            filter_layout.addWidget(input_box, index // 4, index % 4)
        content_layout.addWidget(filter_panel)

        self.library_rows: list[dict[str, str]] = []
        self.library_table = QTableWidget(0, 9)
        self.library_table.setHorizontalHeaderLabels(
            ["缩略图", "编码", "店铺", "尺寸", "DPI", "像素", "原图", "成品图", "生成时间"]
        )
        self._prepare_table(self.library_table)
        self.library_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.library_table.setSortingEnabled(True)
        self.library_table.verticalHeader().setDefaultSectionSize(58)
        content_layout.addWidget(self.library_table)

        layout.addWidget(self.library_content)

        self.library_loading_overlay = QFrame(self.library_content)
        self.library_loading_overlay.setObjectName("LibraryLoadingOverlay")
        overlay_layout = QVBoxLayout(self.library_loading_overlay)
        overlay_layout.setContentsMargins(24, 24, 24, 24)
        overlay_layout.setSpacing(12)
        overlay_layout.addStretch()
        self.library_loading_label = QLabel("正在搜索，请稍候...")
        self.library_loading_label.setObjectName("LoadingLabel")
        self.library_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.library_loading_bar = QProgressBar()
        self.library_loading_bar.setRange(0, 0)
        self.library_loading_bar.setTextVisible(False)
        self.library_loading_bar.setFixedWidth(220)
        overlay_layout.addWidget(self.library_loading_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        overlay_layout.addWidget(self.library_loading_bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        overlay_layout.addStretch()
        self.library_loading_overlay.hide()
        return page

    def _build_print_jobs_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("打印文件", "导入订单文件后，按尺寸和数量自动整理打印图片。"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        panel = self._panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(12)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setVerticalSpacing(8)

        self.print_order_file_input = QLineEdit()
        self.print_output_folder_name_input = QLineEdit()
        self.print_output_folder_name_input.setPlaceholderText("例如：6月21日打印")
        self.print_output_root_input = QLineEdit()
        self.print_quantity_column_combo = QComboBox()
        self.print_code_column_combo = QComboBox()
        self.print_remark_column_1_combo = QComboBox()
        self.print_remark_column_2_combo = QComboBox()
        self.print_order_rows: list[list[str]] = []
        self.print_order_counts: dict[str, int] = {}
        self.print_remark_ignored_codes: list[tuple[str, int]] = []
        self.print_missing_rows: list[dict[str, object]] = []

        for widget in (
            self.print_order_file_input,
            self.print_output_folder_name_input,
            self.print_output_root_input,
            self.print_quantity_column_combo,
            self.print_code_column_combo,
            self.print_remark_column_1_combo,
            self.print_remark_column_2_combo,
        ):
            widget.setMinimumHeight(34)

        form.addRow("订单文件", self._file_row(self.print_order_file_input, "订单文件 (*.xlsx *.csv);;所有文件 (*.*)"))
        form.addRow("打印文件夹名称", self.print_output_folder_name_input)
        form.addRow("输出位置", self._path_row(self.print_output_root_input))
        form.addRow("数量列", self.print_quantity_column_combo)
        form.addRow("图片编码列", self.print_code_column_combo)
        form.addRow("备注列1", self.print_remark_column_1_combo)
        form.addRow("备注列2", self.print_remark_column_2_combo)
        panel_layout.addLayout(form)

        preview_title = QLabel("订单预览")
        preview_title.setObjectName("SectionTitle")
        panel_layout.addWidget(preview_title)

        self.print_preview_table = QTableWidget(0, 0)
        self.print_preview_table.setMinimumHeight(220)
        self.print_preview_table.setMaximumHeight(280)
        self._prepare_table(self.print_preview_table)
        panel_layout.addWidget(self.print_preview_table)

        self.print_progress_label = QLabel("等待开始")
        self.print_progress_label.setObjectName("ProgressHint")
        self.print_progress_bar = QProgressBar()
        self.print_progress_bar.setRange(0, 100)
        self.print_progress_bar.setValue(0)
        self.print_progress_bar.setFormat("%p%")
        panel_layout.addWidget(self.print_progress_label)
        panel_layout.addWidget(self.print_progress_bar)

        self.print_summary_label = QLabel("生成结果会显示在这里。")
        self.print_summary_label.setWordWrap(True)
        self.print_summary_label.setMinimumHeight(84)
        self.print_summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        panel_layout.addWidget(self.print_summary_label)

        action_row = QHBoxLayout()
        preview_button = QPushButton("读取预览")
        preview_button.clicked.connect(self._load_print_order_preview)
        summary_button = QPushButton("先统计")
        summary_button.clicked.connect(self._preview_print_summary)
        start_button = QPushButton("开始生成")
        start_button.setObjectName("PrimaryButton")
        start_button.clicked.connect(self._generate_print_job)
        open_button = QPushButton("打开输出位置")
        open_button.clicked.connect(self._open_print_output_folder)
        action_row.addWidget(preview_button)
        action_row.addWidget(summary_button)
        action_row.addWidget(start_button)
        action_row.addWidget(open_button)
        action_row.addStretch()
        panel_layout.addLayout(action_row)

        panel_layout.addStretch()
        scroll.setWidget(panel)
        layout.addWidget(scroll)
        self.latest_print_output: Path | None = None
        return page

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.webp)",
        )
        if path:
            self._set_selected_image(Path(path))

    def _paste_image_from_clipboard(self) -> None:
        try:
            self.status_label.setText("正在读取剪贴板...")
            QApplication.processEvents()

            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()
            path = self._image_path_from_windows_clipboard()
            if path is None:
                path = self._image_path_from_clipboard_mime(mime_data)
            if path is not None:
                self.status_label.setText(f"已找到剪贴板图片文件：{path}")
                QApplication.processEvents()
                cached_path = self._cache_clipboard_file(path)
                self.status_label.setText(f"已缓存图片文件：{cached_path.name}")
                QApplication.processEvents()
                self._set_selected_image(cached_path)
                self.status_label.setText(f"已粘贴图片文件：{path.name}")
                return

            image = clipboard.image()
            if image.isNull():
                self._warn("剪贴板里没有可用图片。可以复制图片文件，或复制截图/网页图片后再粘贴。")
                return
            paste_dir = self._preview_cache_dir()
            paste_dir.mkdir(parents=True, exist_ok=True)
            path = paste_dir / f"粘贴图片_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            if not image.save(str(path), "PNG"):
                self._warn("保存粘贴图片失败。")
                return
            self._set_selected_image(path)
            self.status_label.setText(f"已粘贴图片：{path.name}")
        except Exception as error:
            self._report_runtime_error("粘贴图片失败", error)

    def _image_path_from_drop(self, mime_data) -> Path | None:  # noqa: ANN001
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if self._is_supported_image_path(path):
                return path
        return None

    def _set_dropped_image(self, path: Path) -> None:
        self._set_selected_image(path)
        self.status_label.setText(f"已拖入图片：{path.name}")

    def _image_path_from_clipboard_mime(self, mime_data) -> Path | None:  # noqa: ANN001
        candidates: list[str] = []

        if mime_data.hasUrls():
            candidates.extend(url.toLocalFile() for url in mime_data.urls() if url.isLocalFile())

        if mime_data.hasText():
            candidates.extend(mime_data.text().replace("\r", "\n").split("\n"))

        if mime_data.hasFormat("text/uri-list"):
            raw = bytes(mime_data.data("text/uri-list")).decode("utf-8", errors="ignore")
            candidates.extend(raw.replace("\r", "\n").split("\n"))

        for candidate in candidates:
            text = candidate.strip().strip('"')
            if not text or text.startswith("#"):
                continue
            if text.lower().startswith("file:///"):
                parsed = urlparse(text)
                text = unquote(parsed.path)
                if len(text) >= 3 and text[0] == "/" and text[2] == ":":
                    text = text[1:]
                text = text.replace("/", "\\")
            path = Path(text)
            if self._is_supported_image_path(path):
                return path
        return None

    def _image_path_from_windows_clipboard(self) -> Path | None:
        for path in self._windows_clipboard_file_paths():
            if self._is_supported_image_path(path):
                return path
        return None

    def _windows_clipboard_file_paths(self) -> list[Path]:
        if sys.platform != "win32":
            return []

        cf_hdrop = 15
        user32 = windll.user32
        shell32 = windll.shell32
        user32.IsClipboardFormatAvailable.argtypes = [c_uint]
        user32.IsClipboardFormatAvailable.restype = c_uint
        user32.OpenClipboard.argtypes = [c_void_p]
        user32.OpenClipboard.restype = c_uint
        user32.GetClipboardData.restype = c_void_p
        user32.CloseClipboard.restype = c_uint
        shell32.DragQueryFileW.argtypes = [c_void_p, c_uint, c_void_p, c_uint]
        shell32.DragQueryFileW.restype = c_uint

        if not user32.IsClipboardFormatAvailable(cf_hdrop):
            return []
        if not user32.OpenClipboard(None):
            return []
        try:
            handle = user32.GetClipboardData(cf_hdrop)
            if not handle:
                return []
            hdrop = c_void_p(handle)
            paths: list[Path] = []
            file_count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
            for index in range(file_count):
                length = shell32.DragQueryFileW(hdrop, index, None, 0)
                buffer = create_unicode_buffer(max(length + 1, MAX_PATH))
                shell32.DragQueryFileW(hdrop, index, buffer, len(buffer))
                paths.append(Path(buffer.value))
            return paths
        finally:
            user32.CloseClipboard()

    def _show_clipboard_diagnostics(self) -> None:
        try:
            report = self._build_clipboard_diagnostics_report()
        except Exception as error:
            report = f"剪贴板诊断失败：{error!r}"

        path = DATA_DIR / "clipboard_diagnostics.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        self.status_label.setText(f"诊断已保存：{path}")
        image_path = self._image_path_from_windows_clipboard()
        if image_path is None:
            image_path = self._image_path_from_clipboard_mime(QApplication.clipboard().mimeData())
        if image_path is not None:
            cached_path = self._cache_clipboard_file(image_path)
            self._set_selected_image(cached_path)
            self._info(f"诊断已保存，并已导入图片：\n{image_path}")
            return
        self._info(f"诊断已保存到：\n{path}")

    def _open_diagnostics_folder(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(DATA_DIR)

    def _build_clipboard_diagnostics_report(self) -> str:
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        lines = ["剪贴板诊断：", ""]

        lines.append(f"Qt hasImage: {not clipboard.image().isNull()}")
        lines.append(f"Qt hasUrls: {mime_data.hasUrls()}")
        if mime_data.hasUrls():
            for url in mime_data.urls():
                lines.append(f"  URL: {url.toString()} | local={url.isLocalFile()} | file={url.toLocalFile()}")

        lines.append(f"Qt hasText: {mime_data.hasText()}")
        if mime_data.hasText():
            text = mime_data.text()
            lines.append(f"  Text: {text[:500]}")

        lines.append("Qt formats:")
        for fmt in mime_data.formats():
            data = bytes(mime_data.data(fmt))
            preview = data[:120].hex(" ")
            lines.append(f"  {fmt} | {len(data)} bytes | {preview}")

        win_paths = self._windows_clipboard_file_paths()
        lines.append("")
        lines.append(f"Windows CF_HDROP files: {len(win_paths)}")
        for path in win_paths:
            lines.append(f"  {path} | exists={path.exists()} | supported={self._is_supported_image_path(path)}")

        return "\n".join(lines)

    def _is_supported_image_path(self, path: Path) -> bool:
        return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and path.exists()

    def _cache_clipboard_file(self, path: Path) -> Path:
        self._cleanup_preview_cache()
        paste_dir = self._preview_cache_dir()
        paste_dir.mkdir(parents=True, exist_ok=True)
        cached_path = paste_dir / f"粘贴文件_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix.lower()}"
        shutil.copy2(path, cached_path)
        return cached_path

    def _preview_cache_dir(self) -> Path:
        return DATA_DIR / "clipboard_uploads"

    def _cleanup_preview_cache(self, max_age_hours: int = 24, max_files: int = 50) -> None:
        cache_dir = self._preview_cache_dir()
        if not cache_dir.exists():
            return

        now = time.time()
        files = [path for path in cache_dir.iterdir() if path.is_file()]
        for path in files:
            try:
                if now - path.stat().st_mtime > max_age_hours * 3600:
                    path.unlink()
            except OSError:
                continue

        files = sorted(
            [path for path in cache_dir.iterdir() if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in files[max_files:]:
            try:
                path.unlink()
            except OSError:
                continue

    def _set_selected_image(self, path: Path) -> None:
        try:
            self.selected_image = path
            self.generated_base_code = None
            self.base_code_input.clear()
            info = read_image_info(path)
            dpi_text = self._format_dpi(info.dpi_x, info.dpi_y)
            self.image_info_label.setText(
                f"{info.width_px} x {info.height_px} px | DPI：{dpi_text} | {info.file_format}"
            )

            pixmap, preview_error = self._load_preview_pixmap(path)
            if pixmap.isNull():
                self.preview_label.clear_preview(f"图片预览失败，但文件已选择。\n{preview_error}")
            else:
                self.preview_label.set_preview_pixmap(pixmap)
            self.preview_label.setFocus()
            self.status_label.setText(f"已选择图片：{path.name}，预览尺寸：{pixmap.width()} x {pixmap.height()}")
        except Exception as error:
            self._report_runtime_error("选择图片失败", error)

    def _load_preview_pixmap(self, path: Path) -> tuple[QPixmap, str]:
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGBA")
                image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                pixmap = QPixmap()
                if pixmap.loadFromData(buffer.getvalue(), "PNG"):
                    return pixmap, ""
                return QPixmap(), "Qt 无法从缩略图数据加载预览。"
        except Exception as error:
            return QPixmap(), str(error)

    def _format_dpi(self, dpi_x: float | None, dpi_y: float | None) -> str:
        if not dpi_x or not dpi_y:
            return "未设置"
        try:
            return f"{float(dpi_x):g} x {float(dpi_y):g}"
        except (TypeError, ValueError):
            return f"{dpi_x} x {dpi_y}"

    def _report_runtime_error(self, title: str, error: Exception) -> None:
        path = DATA_DIR / "last_error.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        message = f"{title}：{error!r}"
        path.write_text(message, encoding="utf-8")
        self.status_label.setText(f"{title}，错误已保存：{path}")
        self._warn(f"{message}\n\n错误已保存到：\n{path}")

    def _generate_code(self) -> None:
        shop = self._selected_shop()
        if shop is None:
            self._warn("请先新增或选择一个店铺。")
            return
        try:
            sequence = next_sequence(load_base_codes(), shop.prefix)
            self.generated_base_code = make_base_code(shop.prefix, sequence)
            self.base_code_input.setText(self.generated_base_code)
            self.status_label.setText(f"已生成编码：{self.generated_base_code}")
        except ValueError as error:
            self._warn(str(error))

    def _generate_images(self) -> None:
        if self.selected_image is None:
            self._warn("请先选择图片。")
            return
        shop = self._selected_shop()
        if shop is None:
            self._warn("请先新增或选择一个店铺。")
            return
        base_code = self.base_code_input.text().strip().upper()
        if not base_code:
            self._generate_code()
            base_code = self.base_code_input.text().strip().upper()
        sizes = self._selected_sizes()
        if not sizes:
            self._warn("请至少选择一个尺寸。")
            return

        try:
            info = read_image_info(self.selected_image)
            shop.original_folder.mkdir(parents=True, exist_ok=True)
            shop.output_folder.mkdir(parents=True, exist_ok=True)

            original_copy = shop.original_folder / f"{self.selected_image.stem}.jpg"
            with Image.open(self.selected_image) as original_image:
                converted_original = ImageOps.exif_transpose(original_image).convert("RGB")
                converted_original.save(original_copy, format="JPEG", quality=95)

            created = 0
            for size in sizes:
                full_code = make_full_code(base_code, size)
                output_dir = shop.output_folder / size.code_suffix
                output_path = output_dir / f"{full_code}.jpg"
                output_width, output_height = generate_sized_image(
                    original_copy,
                    output_path,
                    size,
                    label=full_code,
                )
                append_index_row(
                    ImageIndexRow(
                        shop_name=shop.name,
                        shop_prefix=shop.prefix,
                        base_code=base_code,
                        full_code=full_code,
                        original_name=original_copy.name,
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
            self.status_label.setText(f"已生成 {created} 个图片文件。")
            self._refresh_all()
            self._info(f"已生成 {created} 个图片文件。")
        except Exception as error:
            self._warn(f"生成图片失败：{error}")

    def _save_shop(self) -> None:
        try:
            prefix = normalize_shop_prefix(self.shop_prefix_input.text())
        except ValueError as error:
            self._warn(str(error))
            return
        name = self.shop_name_input.text().strip()
        if not name:
            self._warn("请填写店铺名称。")
            return
        original_folder = Path(self.original_folder_input.text().strip())
        output_folder = Path(self.output_folder_input.text().strip())
        if not str(original_folder) or not str(output_folder):
            self._warn("请填写原图文件夹和成品图文件夹。")
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
        self.status_label.setText(f"已保存店铺：{shop.name}")
        self._refresh_all()

    def _selected_shop(self) -> Shop | None:
        index = self.upload_shop_combo.currentIndex()
        if index < 0 or index >= len(self.shops):
            return None
        return self.shops[index]

    def _selected_sizes(self) -> list[SizeSpec]:
        return [
            SizeSpec(width_spin.value(), height_spin.value(), dpi_spin.value())
            for _row_frame, width_spin, height_spin, dpi_spin in self.size_rows
        ]

    def _add_size_row(self, width: int, height: int, dpi: int) -> None:
        row_frame = QFrame()
        row_frame.setObjectName("SizeRow")
        row_frame.setFixedHeight(58)
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(8)

        width_spin = self._size_input(width, 1, 300)
        height_spin = self._size_input(height, 1, 300)
        dpi_spin = self._size_input(dpi, 72, 600)

        row_layout.addWidget(QLabel("宽"))
        row_layout.addWidget(width_spin)
        row_layout.addWidget(QLabel("cm"))
        row_layout.addSpacing(6)
        row_layout.addWidget(QLabel("高"))
        row_layout.addWidget(height_spin)
        row_layout.addWidget(QLabel("cm"))
        row_layout.addSpacing(6)
        row_layout.addWidget(QLabel("DPI"))
        row_layout.addWidget(dpi_spin)
        row_layout.addStretch()

        delete_button = QPushButton()
        delete_button.setObjectName("DeleteButton")
        delete_button.setText("删除")
        delete_button.clicked.connect(lambda checked=False, frame=row_frame: self._delete_size_row(frame))
        row_layout.addWidget(delete_button)

        self.size_rows.append((row_frame, width_spin, height_spin, dpi_spin))
        self.size_list_layout.insertWidget(max(0, self.size_list_layout.count() - 1), row_frame)

    def _delete_size_row(self, row_frame: QFrame) -> None:
        for index, (frame, _width, _height, _dpi) in enumerate(self.size_rows):
            if frame is row_frame:
                self.size_rows.pop(index)
                frame.setParent(None)
                frame.deleteLater()
                return

    def _size_input(self, value: int, minimum: int, maximum: int) -> SizeNumberInput:
        return SizeNumberInput(value, minimum, maximum)

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
                "是" if shop.enabled else "否",
            ]
            for column, value in enumerate(values):
                self.shop_table.setItem(row, column, QTableWidgetItem(value))

    def _refresh_library(self) -> None:
        self._set_library_loading(True)
        rows = self._filtered_library_rows(load_index_rows())
        self.library_table.setSortingEnabled(False)
        self.library_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                "",
                row.get("full_code", ""),
                row.get("shop_name", ""),
                f"{row.get('width_cm', '')} x {row.get('height_cm', '')}",
                row.get("dpi", ""),
                f"{row.get('output_width_px', '')} x {row.get('output_height_px', '')}",
                row.get("original_name", ""),
                row.get("output_path", ""),
                row.get("created_at", ""),
            ]
            thumbnail = self._library_thumbnail(row.get("output_path", ""))
            thumbnail_label = QLabel()
            thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if not thumbnail.isNull():
                thumbnail_label.setPixmap(
                    thumbnail.scaled(
                        46,
                        46,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            self.library_table.setCellWidget(row_index, 0, thumbnail_label)
            for column, value in enumerate(values):
                self.library_table.setItem(row_index, column, QTableWidgetItem(value))
        self.library_table.setSortingEnabled(True)
        self._set_library_loading(False)

    def _filtered_library_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        if not hasattr(self, "library_filters"):
            return rows
        filtered: list[dict[str, str]] = []
        for row in rows:
            row_values = {
                "full_code": row.get("full_code", ""),
                "shop_name": row.get("shop_name", ""),
                "size": f"{row.get('width_cm', '')} x {row.get('height_cm', '')}",
                "dpi": row.get("dpi", ""),
                "pixels": f"{row.get('output_width_px', '')} x {row.get('output_height_px', '')}",
                "original_name": row.get("original_name", ""),
                "output_path": row.get("output_path", ""),
                "created_at": row.get("created_at", ""),
            }
            if all(
                filter_box.text().strip().lower() in row_values[key].lower()
                for key, filter_box in self.library_filters.items()
                if filter_box.text().strip()
            ):
                filtered.append(row)
        return filtered

    def _clear_library_filters(self) -> None:
        if not hasattr(self, "library_filters"):
            return
        for filter_box in self.library_filters.values():
            filter_box.clear()
        self._refresh_library()

    def _delete_selected_library_rows(self) -> None:
        selected_rows = sorted({index.row() for index in self.library_table.selectionModel().selectedRows()})
        if not selected_rows:
            self._warn("请先在图片库中选择要删除的记录。")
            return

        selected_codes = {
            self.library_table.item(row, 1).text().strip().upper()
            for row in selected_rows
            if self.library_table.item(row, 1)
        }
        if not selected_codes:
            self._warn("没有读取到可删除的图片编码。")
            return

        choice = QMessageBox.question(
            self,
            "图片仓库",
            "是否同时删除对应的成品图文件？\n\n选择“是”会删除记录和成品图文件。\n选择“否”只删除图片库记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return

        remove_files = choice == QMessageBox.StandardButton.Yes
        rows = load_index_rows()
        rows_to_delete = [
            row for row in rows if row.get("full_code", "").strip().upper() in selected_codes
        ]
        if remove_files:
            for row in rows_to_delete:
                output_path = Path(row.get("output_path", ""))
                if output_path.exists():
                    output_path.unlink()

        remaining_rows = delete_index_rows(rows, selected_codes)
        save_index_rows(remaining_rows)
        self.status_label.setText(f"已删除 {len(selected_codes)} 条图片记录")
        self._refresh_all()

    def _set_library_loading(self, visible: bool) -> None:
        if not hasattr(self, "library_loading_overlay"):
            return
        self.library_loading_overlay.setGeometry(self.library_content.rect())
        self.library_loading_overlay.setVisible(visible)
        QApplication.processEvents()

    def _set_print_progress(self, value: int, text: str) -> None:
        if not hasattr(self, "print_progress_bar"):
            return
        self.print_progress_bar.setValue(value)
        self.print_progress_label.setText(text)
        self.status_label.setText(text)
        QApplication.processEvents()

    def _load_print_order_preview(self) -> None:
        order_path_text = self.print_order_file_input.text().strip()
        if not order_path_text:
            self._warn("请先选择订单文件。")
            return

        order_path = Path(order_path_text)
        if not order_path.exists():
            self._warn("订单文件不存在，请重新选择。")
            return

        try:
            self._set_print_progress(10, "正在读取订单预览...")
            rows = load_order_rows(order_path)
            self.print_order_rows = rows
            self.print_order_counts = {}
            self.print_remark_ignored_codes = []
            self.print_missing_rows = []
            self._populate_print_preview(rows)
            self._populate_print_column_combos(rows)
            self.print_summary_label.setText("已读取订单预览，请确认数量列和图片编码列。")
            self._set_print_progress(25, "预览已加载")
        except Exception as error:
            self._set_print_progress(0, "读取预览失败")
            self._warn(f"读取订单预览失败：{error}")

    def _populate_print_preview(self, rows: list[list[str]], preview_limit: int = 8) -> None:
        column_count = max((len(row) for row in rows[:preview_limit]), default=0)
        self.print_preview_table.setColumnCount(column_count)
        self.print_preview_table.setRowCount(min(len(rows), preview_limit))
        for row_index, row in enumerate(rows[:preview_limit]):
            for column_index in range(column_count):
                value = row[column_index] if column_index < len(row) else ""
                self.print_preview_table.setItem(row_index, column_index, QTableWidgetItem(str(value).strip()))
        if rows:
            headers = []
            header_row = rows[0]
            for column_index in range(column_count):
                header_text = header_row[column_index].strip() if column_index < len(header_row) else ""
                headers.append(header_text or f"第{column_index + 1}列")
            self.print_preview_table.setHorizontalHeaderLabels(headers)

    def _populate_print_column_combos(self, rows: list[list[str]]) -> None:
        self.print_quantity_column_combo.clear()
        self.print_code_column_combo.clear()
        self.print_remark_column_1_combo.clear()
        self.print_remark_column_2_combo.clear()
        column_count = max((len(row) for row in rows), default=0)
        headers = rows[0] if rows else []
        self.print_remark_column_1_combo.addItem("不使用", -1)
        self.print_remark_column_2_combo.addItem("不使用", -1)
        for index in range(column_count):
            header_text = headers[index].strip() if index < len(headers) else ""
            label = f"第{index + 1}列"
            if header_text:
                label = f"{label} - {header_text}"
            self.print_quantity_column_combo.addItem(label, index)
            self.print_code_column_combo.addItem(label, index)
            self.print_remark_column_1_combo.addItem(label, index)
            self.print_remark_column_2_combo.addItem(label, index)

        quantity_index, code_index = detect_default_columns(rows)
        self.print_quantity_column_combo.setCurrentIndex(max(0, quantity_index))
        self.print_code_column_combo.setCurrentIndex(max(0, code_index))
        if self.print_remark_column_1_combo.count() > 5:
            self.print_remark_column_1_combo.setCurrentIndex(5)
        if self.print_remark_column_2_combo.count() > 6:
            self.print_remark_column_2_combo.setCurrentIndex(6)

    def _preview_print_summary(self) -> None:
        if not self.print_order_rows:
            self._load_print_order_preview()
            if not self.print_order_rows:
                return

        try:
            self._set_print_progress(45, "正在统计订单...")
            quantity_column = self.print_quantity_column_combo.currentData()
            code_column = self.print_code_column_combo.currentData()
            remark_columns = [
                value
                for value in (
                    self.print_remark_column_1_combo.currentData(),
                    self.print_remark_column_2_combo.currentData(),
                )
                if isinstance(value, int) and value >= 0
            ]
            parsed = parse_order_rows_with_remarks(
                self.print_order_rows,
                quantity_column=int(quantity_column),
                code_column=int(code_column),
                skip_header=True,
                remark_columns=remark_columns,
            )
            if not parsed.order_counts and not parsed.missing_rows:
                self.print_order_counts = {}
                self.print_remark_ignored_codes = []
                self.print_missing_rows = []
                self.print_summary_label.setText("当前列设置下，没有识别到可用编码。请检查数量列和图片编码列。")
                self._set_print_progress(0, "等待开始")
                return

            self.print_order_counts = parsed.order_counts
            self.print_remark_ignored_codes = parsed.remark_ignored_codes
            self.print_missing_rows = parsed.missing_rows
            summary = summarize_order_counts(parsed.order_counts)
            preview_lines = [f"{code} x {quantity}" for code, quantity in summary.preview_rows[:10]]
            preview_text = "\n".join(preview_lines)
            self.print_summary_label.setText(
                f"已统计 {summary.total_codes} 个编码，合计 {summary.total_copies} 张。\n"
                f"未匹配行 {len(parsed.missing_rows)} 条。\n\n"
                f"前几项预览：\n{preview_text}"
            )
            self._set_print_progress(60, "统计完成")
        except Exception as error:
            self.print_order_counts = {}
            self.print_remark_ignored_codes = []
            self.print_missing_rows = []
            self._set_print_progress(0, "统计失败")
            self._warn(f"统计订单失败：{error}")

    def _generate_print_job(self) -> None:
        order_path_text = self.print_order_file_input.text().strip()
        folder_name = self.print_output_folder_name_input.text().strip()
        output_root_text = self.print_output_root_input.text().strip()

        if not order_path_text:
            self._warn("请先选择订单文件。")
            return
        if not folder_name:
            self._warn("请填写打印文件夹名称。")
            return
        if not output_root_text:
            self._warn("请先选择输出位置。")
            return

        order_path = Path(order_path_text)
        output_root = Path(output_root_text)
        if not order_path.exists():
            self._warn("订单文件不存在，请重新选择。")
            return

        try:
            if not self.print_order_rows:
                self._load_print_order_preview()
                if not self.print_order_rows:
                    return
            if not self.print_order_counts:
                self._preview_print_summary()
                if not self.print_order_counts:
                    return

            self._set_print_progress(55, "正在匹配图片库记录...")
            index_rows = load_index_rows()

            self._set_print_progress(80, "正在生成打印文件夹...")
            result = build_print_job(
                order_counts=self.print_order_counts,
                index_rows=index_rows,
                output_root=output_root,
                folder_name=folder_name,
                forced_missing_codes=self.print_remark_ignored_codes,
                source_headers=self.print_order_rows[0] if self.print_order_rows else [],
                missing_rows=self.print_missing_rows,
            )

            self.latest_print_output = result.output_folder
            self._set_print_progress(100, "生成完成")
            missing_count = len(result.missing_codes)
            self.print_summary_label.setText(
                f"已生成 {result.completed_codes} 个编码，合计 {result.total_copies} 张。\n"
                f"未匹配编码 {missing_count} 个。\n"
                f"输出位置：{result.output_folder}"
            )
            self._info(
                f"打印文件已生成。\n\n已生成编码：{result.completed_codes}\n"
                f"未匹配编码：{missing_count}\n\n输出位置：\n{result.output_folder}"
            )
        except Exception as error:
            self._set_print_progress(0, "生成失败")
            self._warn(f"生成打印文件失败：{error}")

    def _open_print_output_folder(self) -> None:
        if self.latest_print_output is None or not self.latest_print_output.exists():
            self._warn("当前还没有可打开的输出文件夹。")
            return
        os.startfile(self.latest_print_output)

    def _library_thumbnail(self, path_text: str) -> QPixmap:
        path = Path(path_text)
        if not path.exists():
            return QPixmap()
        pixmap, _error = self._load_preview_pixmap(path)
        return pixmap

    def _set_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def _path_row(self, line_edit: QLineEdit) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        browse = QPushButton("浏览")
        browse.setMinimumHeight(34)
        browse.clicked.connect(lambda: self._browse_folder(line_edit))
        layout.addWidget(line_edit)
        layout.addWidget(browse)
        return container

    def _file_row(self, line_edit: QLineEdit, file_filter: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        browse = QPushButton("选择文件")
        browse.setMinimumHeight(34)
        browse.clicked.connect(lambda: self._browse_file(line_edit, file_filter))
        layout.addWidget(line_edit)
        layout.addWidget(browse)
        return container

    def _browse_folder(self, line_edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            line_edit.setText(folder)

    def _browse_file(self, line_edit: QLineEdit, file_filter: str) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if file_path:
            line_edit.setText(file_path)
            if hasattr(self, "print_order_file_input") and line_edit is self.print_order_file_input:
                self.print_order_rows = []
                self.print_order_counts = {}
                self.print_remark_ignored_codes = []
                self.print_missing_rows = []
                if hasattr(self, "print_preview_table"):
                    self.print_preview_table.setRowCount(0)
                    self.print_preview_table.setColumnCount(0)
                if hasattr(self, "print_summary_label"):
                    self.print_summary_label.setText("生成结果会显示在这里。")
                if hasattr(self, "print_progress_bar"):
                    self.print_progress_bar.setValue(0)
                if hasattr(self, "print_progress_label"):
                    self.print_progress_label.setText("等待开始")

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
        QMessageBox.warning(self, "图片仓库", text)

    def _info(self, text: str) -> None:
        QMessageBox.information(self, "图片仓库", text)

    def _save_shop(self) -> None:
        try:
            prefix = normalize_shop_prefix(self.shop_prefix_input.text())
        except ValueError as error:
            self._warn(str(error))
            return

        name = self.shop_name_input.text().strip()
        if not name:
            self._warn("请填写店铺名称。")
            return

        original_folder = Path(self.original_folder_input.text().strip())
        output_folder = Path(self.output_folder_input.text().strip())
        if not str(original_folder) or not str(output_folder):
            self._warn("请填写原图文件夹和成品图文件夹。")
            return

        editing_prefix = self.editing_shop_prefix
        for item in self.shops:
            if item.prefix == prefix and item.prefix != editing_prefix:
                self._warn("店铺前缀已存在，请更换一个前缀。")
                return

        shop = Shop(
            name=name,
            short_name=self.shop_short_input.text().strip() or name,
            prefix=prefix,
            original_folder=original_folder,
            output_folder=output_folder,
        )
        if editing_prefix:
            self.shops = [item for item in self.shops if item.prefix != editing_prefix]
        else:
            self.shops = [item for item in self.shops if item.prefix != prefix]
        self.shops.append(shop)
        save_shops(self.shops)
        self._clear_shop_form()
        self.status_label.setText(f"已保存店铺：{shop.name}")
        self._refresh_all()

    def _selected_shop_for_manage(self) -> Shop | None:
        if self.editing_shop_prefix:
            for shop in self.shops:
                if shop.prefix == self.editing_shop_prefix:
                    return shop
        row = self.shop_table.currentRow()
        if row < 0 or row >= len(self.shops):
            return None
        return self.shops[row]

    def _on_shop_selection_changed(self) -> None:
        shop = self._selected_shop_for_manage()
        if shop is not None:
            self._load_shop_into_form(shop)

    def _load_shop_into_form(self, shop: Shop) -> None:
        self.editing_shop_prefix = shop.prefix
        self.shop_name_input.setText(shop.name)
        self.shop_short_input.setText(shop.short_name)
        self.shop_prefix_input.setText(shop.prefix)
        self.original_folder_input.setText(str(shop.original_folder))
        self.output_folder_input.setText(str(shop.output_folder))
        self.status_label.setText(f"已选中店铺：{shop.name}")

    def _clear_shop_form(self) -> None:
        self.editing_shop_prefix = None
        self.shop_name_input.clear()
        self.shop_short_input.clear()
        self.shop_prefix_input.clear()
        self.original_folder_input.clear()
        self.output_folder_input.clear()
        if hasattr(self, "shop_table"):
            self.shop_table.blockSignals(True)
            self.shop_table.clearSelection()
            self.shop_table.blockSignals(False)

    def _migrate_shop_library(self) -> None:
        shop = self._selected_shop_for_manage()
        if shop is None:
            self._warn("请先在店铺表格中选择一个店铺。")
            return

        new_original_folder = Path(self.original_folder_input.text().strip())
        new_output_folder = Path(self.output_folder_input.text().strip())
        if not str(new_original_folder) or not str(new_output_folder):
            self._warn("请先填写新的原图和成品图文件夹路径。")
            return

        if new_original_folder == shop.original_folder and new_output_folder == shop.output_folder:
            self._warn("新的文件夹路径与当前一致，无需迁移。")
            return

        confirmed = QMessageBox.question(
            self,
            "图片仓库",
            f"将迁移店铺“{shop.name}”的图片库，并同步更新图片索引。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        try:
            moved_original = self._move_folder_contents(shop.original_folder, new_original_folder)
            moved_output = self._move_folder_contents(shop.output_folder, new_output_folder)
            updated_prefix = normalize_shop_prefix(self.shop_prefix_input.text())
            updated_name = self.shop_name_input.text().strip() or shop.name
            self._rewrite_shop_index_paths(
                shop,
                updated_name,
                updated_prefix,
                new_original_folder,
                new_output_folder,
            )
            updated_shop = Shop(
                name=updated_name,
                short_name=self.shop_short_input.text().strip() or updated_name,
                prefix=updated_prefix,
                original_folder=new_original_folder,
                output_folder=new_output_folder,
                enabled=shop.enabled,
                remark=shop.remark,
            )
            self.shops = [item for item in self.shops if item.prefix != shop.prefix]
            self.shops.append(updated_shop)
            save_shops(self.shops)
            self.editing_shop_prefix = updated_shop.prefix
            self.status_label.setText(f"已完成迁移：原图 {moved_original} 项，成品图 {moved_output} 项")
            self._refresh_all()
            self._load_shop_into_form(updated_shop)
            self._info("图片库迁移完成，图库索引也已同步更新。")
        except Exception as error:
            self._warn(f"迁移失败：{error}")

    def _move_folder_contents(self, source: Path, target: Path) -> int:
        source = source.expanduser()
        target = target.expanduser()
        target.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            return 0
        try:
            if source.resolve() == target.resolve():
                return 0
        except OSError:
            pass

        moved_count = 0
        for item in list(source.iterdir()):
            destination = target / item.name
            if destination.exists():
                if item.is_dir() and destination.is_dir():
                    moved_count += self._move_folder_contents(item, destination)
                    if item.exists() and not any(item.iterdir()):
                        item.rmdir()
                    continue
                raise FileExistsError(f"目标中已存在同名文件：{destination}")
            shutil.move(str(item), str(destination))
            moved_count += 1
        return moved_count

    def _rewrite_shop_index_paths(
        self,
        shop: Shop,
        updated_name: str,
        updated_prefix: str,
        new_original_folder: Path,
        new_output_folder: Path,
    ) -> None:
        rows = load_index_rows()
        updated_rows: list[dict[str, str]] = []
        old_original = str(shop.original_folder)
        old_output = str(shop.output_folder)
        for row in rows:
            updated_row = dict(row)
            if row.get("shop_prefix") == shop.prefix:
                updated_row["shop_name"] = updated_name
                updated_row["shop_prefix"] = updated_prefix
                updated_row["original_path"] = self._replace_index_path(
                    row.get("original_path", ""),
                    old_original,
                    str(new_original_folder),
                )
                updated_row["output_path"] = self._replace_index_path(
                    row.get("output_path", ""),
                    old_output,
                    str(new_output_folder),
                )
            updated_rows.append(updated_row)
        save_index_rows(updated_rows)

    def _replace_index_path(self, value: str, old_root: str, new_root: str) -> str:
        if not value:
            return value
        try:
            relative = Path(value).relative_to(Path(old_root))
        except (ValueError, OSError):
            return value
        return str(Path(new_root) / relative)

    def _refresh_shops_table(self) -> None:
        self.shop_table.setRowCount(len(self.shops))
        selected_row = -1
        for row, shop in enumerate(self.shops):
            values = [
                shop.name,
                shop.prefix,
                str(shop.original_folder),
                str(shop.output_folder),
                "是" if shop.enabled else "否",
            ]
            for column, value in enumerate(values):
                self.shop_table.setItem(row, column, QTableWidgetItem(value))
            if self.editing_shop_prefix and shop.prefix == self.editing_shop_prefix:
                selected_row = row
        if selected_row >= 0:
            self.shop_table.blockSignals(True)
            self.shop_table.selectRow(selected_row)
            self.shop_table.blockSignals(False)

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
                padding: 18px;
            }
            #Preview:focus {
                border: 2px solid #2f6f5f;
            }
            #SizeScroll {
                background: transparent;
                border: none;
            }
            #SizeList {
                background: transparent;
            }
            #SizeRow {
                background: #f7faf8;
                border: 1px solid #dfe7e2;
                border-radius: 8px;
            }
            #LibraryLoadingOverlay {
                background: rgba(246, 247, 244, 220);
                border: 1px solid #dde4df;
                border-radius: 8px;
            }
            #LoadingLabel {
                font-size: 15px;
                font-weight: 600;
                color: #25332f;
                background: transparent;
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
            #DeleteButton {
                color: #9a3028;
                background: #fff8f7;
                border: 1px solid #efc8c3;
                padding: 7px 10px;
            }
            #DeleteButton:hover {
                background: #fdecea;
            }
            #SizeNumberInput {
                padding: 7px 6px;
            }
            #SizeStepButton {
                min-width: 24px;
                max-width: 24px;
                min-height: 32px;
                max-height: 32px;
                padding: 0;
                font-weight: 700;
            }
            QLineEdit, QComboBox, QSpinBox {
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
