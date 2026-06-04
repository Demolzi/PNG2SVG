from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from batch_cutout_svg.models import ImageItem


class ImageListPanel(QWidget):
    def __init__(
        self,
        on_select: Callable[[Path], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self._suppress_selection_callback = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(QLabel("图片列表"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件", "区域", "导出"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._handle_select)
        layout.addWidget(self.table, 1)

    def set_images(self, items: list[ImageItem]) -> None:
        current_selection = self.selected_path()
        self._suppress_selection_callback = True
        try:
            self.table.setRowCount(0)
            for item in items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                name_item = QTableWidgetItem(item.file_name)
                name_item.setData(Qt.ItemDataRole.UserRole, str(item.path))
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, _center_item(str(len(item.regions))))
                self.table.setItem(row, 2, _center_item("是" if item.exported else "否"))
            if current_selection is not None:
                self.select_path(current_selection, notify=False)
        finally:
            QTimer.singleShot(10, self._clear_selection_suppression)

    def select_path(self, path: Path, notify: bool = True) -> None:
        row = self._row_for_path(path)
        if row is None:
            return
        if not notify:
            self._suppress_selection_callback = True
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 0))
        if not notify:
            QTimer.singleShot(10, self._clear_selection_suppression)

    def selected_path(self) -> Path | None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.table.item(selected_rows[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return Path(str(value)) if value else None

    def _handle_select(self) -> None:
        if self._suppress_selection_callback:
            return
        selected = self.selected_path()
        if selected is not None:
            self.on_select(selected)

    def _row_for_path(self, path: Path) -> int | None:
        path_value = str(path)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == path_value:
                return row
        return None

    def _clear_selection_suppression(self) -> None:
        self._suppress_selection_callback = False


def _center_item(value: str) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
