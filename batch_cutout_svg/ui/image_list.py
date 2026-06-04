from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from batch_cutout_svg.models import ImageItem

COL_PATH = 0
COL_FILE = 1
COL_REGIONS = 2
COL_EXPORTED = 3
EXPANDED_MIN_WIDTH = 280
COLLAPSED_WIDTH = 96


class ImageListPanel(QWidget):
    def __init__(
        self,
        on_select: Callable[[Path], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self._suppress_selection_callback = False
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.title_label = QLabel("图片列表")
        self.toggle_button = QPushButton("收起")
        self.toggle_button.setFixedWidth(72)
        self.toggle_button.setStyleSheet(
            "QPushButton { text-align: center; padding-left: 0px; padding-right: 0px; }"
        )
        self.toggle_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.toggle_button)
        layout.addLayout(header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["序号", "文件", "区域", "导出"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_REGIONS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_EXPORTED, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._handle_select)
        layout.addWidget(self.table, 1)
        self._apply_collapsed_state()

    def set_images(self, items: list[ImageItem]) -> None:
        current_selection = self.selected_path()
        self._suppress_selection_callback = True
        try:
            self.table.setRowCount(0)
            for index, item in enumerate(items, start=1):
                row = self.table.rowCount()
                self.table.insertRow(row)
                path_value = str(item.path)
                self.table.setItem(row, COL_PATH, _center_item(str(index), path_value))
                self.table.setItem(row, COL_FILE, _item(item.file_name, path_value))
                self.table.setItem(row, COL_REGIONS, _center_item(str(len(item.regions)), path_value))
                self.table.setItem(row, COL_EXPORTED, _center_item("是" if item.exported else "否", path_value))
            if current_selection is not None:
                self.select_path(current_selection, notify=False)
        finally:
            QTimer.singleShot(10, self._clear_selection_suppression)

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self._apply_collapsed_state()

    def select_path(self, path: Path, notify: bool = True) -> None:
        row = self._row_for_path(path)
        if row is None:
            return
        if not notify:
            self._suppress_selection_callback = True
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, COL_PATH))
        if not notify:
            QTimer.singleShot(10, self._clear_selection_suppression)

    def selected_path(self) -> Path | None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.table.item(selected_rows[0].row(), COL_PATH)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return Path(str(value)) if value else None

    def _apply_collapsed_state(self) -> None:
        self.title_label.setVisible(not self._collapsed)
        self.title_label.setText("图片列表")
        self.toggle_button.setText("展开" if self._collapsed else "收起")
        for column in (COL_FILE, COL_REGIONS, COL_EXPORTED):
            self.table.setColumnHidden(column, self._collapsed)
        self.table.horizontalHeader().setVisible(not self._collapsed)
        if self._collapsed:
            self.setMinimumWidth(COLLAPSED_WIDTH)
            self.setMaximumWidth(COLLAPSED_WIDTH)
            self.table.horizontalHeader().setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Stretch)
        else:
            self.setMinimumWidth(EXPANDED_MIN_WIDTH)
            self.setMaximumWidth(16_777_215)
            self.table.horizontalHeader().setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.ResizeToContents)
            self.table.resizeColumnsToContents()
        self.updateGeometry()

    def _handle_select(self) -> None:
        if self._suppress_selection_callback:
            return
        selected = self.selected_path()
        if selected is not None:
            self.on_select(selected)

    def _row_for_path(self, path: Path) -> int | None:
        path_value = str(path)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_PATH)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == path_value:
                return row
        return None

    def _clear_selection_suppression(self) -> None:
        self._suppress_selection_callback = False


def _item(value: str, path_value: str) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setData(Qt.ItemDataRole.UserRole, path_value)
    return item


def _center_item(value: str, path_value: str) -> QTableWidgetItem:
    item = _item(value, path_value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
