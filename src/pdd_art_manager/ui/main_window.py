from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdd_art_manager.config import APP_NAME, ensure_app_dirs


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dirs()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 680)
        self.setCentralWidget(self._build_home())

    def _build_home(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("装饰画图片管理")
        title.setStyleSheet("font-size: 26px; font-weight: 600;")

        subtitle = QLabel("管理店铺图片、自动生成编码，并批量生成不同尺寸。")
        subtitle.setStyleSheet("font-size: 14px; color: #555;")

        upload_button = QPushButton("上传图片")
        shop_button = QPushButton("店铺管理")
        library_button = QPushButton("图片库")

        for button in (upload_button, shop_button, library_button):
            button.setMinimumHeight(40)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        layout.addWidget(upload_button)
        layout.addWidget(shop_button)
        layout.addWidget(library_button)

        return root

