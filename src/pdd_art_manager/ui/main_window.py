from __future__ import annotations

import shutil
import sys
import os
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
from pdd_art_manager.services.index_store import append_index_row, load_base_codes, load_index_rows
from pdd_art_manager.services.shop_store import load_shops, save_shops
from PIL import Image, ImageOps


DEFAULT_SIZES = [(20, 30), (30, 40), (40, 60)]


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
        self.shops = load_shops()
        self.selected_image: Path | None = None
        self.generated_base_code: str | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)
        self._apply_style()
        self.setCentralWidget(self._build_shell())
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.activated.connect(self._paste_image_from_clipboard)
        QApplication.instance().installEventFilter(self)
        self._refresh_all()

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001, N802
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
        nav_items = [("总览", 0), ("上传图片", 1), ("店铺管理", 2), ("图片库", 3)]
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

        size_scroll = QScrollArea()
        size_scroll.setObjectName("SizeScroll")
        size_scroll.setWidgetResizable(True)
        size_scroll.setFrameShape(QFrame.Shape.NoFrame)
        size_scroll.setMinimumHeight(190)
        size_scroll.setMaximumHeight(250)
        size_scroll.setWidget(self.size_list)
        form_layout.addWidget(size_scroll)
        for width, height in DEFAULT_SIZES:
            self._add_size_row(width, height, 150)

        self.generate_button = QPushButton("生成所选尺寸")
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

    def _build_library_page(self) -> QWidget:
        page = self._page()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._page_title("图片库", "这里显示保存在本地 CSV 索引中的图片生成记录。"))

        toolbar = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_library)
        toolbar.addWidget(refresh)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.library_table = QTableWidget(0, 8)
        self.library_table.setHorizontalHeaderLabels(
            ["编码", "店铺", "尺寸", "DPI", "像素", "原图", "成品图", "生成时间"]
        )
        self._prepare_table(self.library_table)
        layout.addWidget(self.library_table)
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
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        path = self._image_path_from_windows_clipboard()
        if path is None:
            path = self._image_path_from_clipboard_mime(mime_data)
        if path is not None:
            cached_path = self._cache_clipboard_file(path)
            self._set_selected_image(cached_path)
            self.status_label.setText(f"已粘贴图片文件：{path.name}")
            return

        image = clipboard.image()
        if image.isNull():
            self._warn("剪贴板里没有可用图片。可以复制图片文件，或复制截图/网页图片后再粘贴。")
            return
        paste_dir = DATA_DIR / "clipboard_uploads"
        paste_dir.mkdir(parents=True, exist_ok=True)
        path = paste_dir / f"粘贴图片_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not image.save(str(path), "PNG"):
            self._warn("保存粘贴图片失败。")
            return
        self._set_selected_image(path)
        self.status_label.setText(f"已粘贴图片：{path.name}")

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
        paste_dir = DATA_DIR / "clipboard_uploads"
        paste_dir.mkdir(parents=True, exist_ok=True)
        cached_path = paste_dir / f"粘贴文件_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix.lower()}"
        shutil.copy2(path, cached_path)
        return cached_path

    def _set_selected_image(self, path: Path) -> None:
        self.selected_image = path
        info = read_image_info(path)
        dpi_text = f"{info.dpi_x:g} x {info.dpi_y:g}" if info.dpi_x and info.dpi_y else "未设置"
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
        self.size_list_layout.addWidget(row_frame)

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
        browse = QPushButton("浏览")
        browse.clicked.connect(lambda: self._browse_folder(line_edit))
        layout.addWidget(line_edit)
        layout.addWidget(browse)
        return container

    def _browse_folder(self, line_edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
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
        QMessageBox.warning(self, "图片仓库", text)

    def _info(self, text: str) -> None:
        QMessageBox.information(self, "图片仓库", text)

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
