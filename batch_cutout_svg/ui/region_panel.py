from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from batch_cutout_svg.core.mask import CutoutOptions
from batch_cutout_svg.models import Region

COL_CHECKED = 0
COL_NAME = 1
COL_TYPE = 2
COL_VISIBLE = 3
COL_EXPORT_COUNT = 4
COL_STATUS = 5


class RegionPanel(QWidget):
    def __init__(
        self,
        on_select: Callable[[str | None], None],
        on_rename: Callable[[str], None],
        on_toggle_visible: Callable[[], None],
        on_delete: Callable[[], None],
        on_browse_output: Callable[[], None],
        on_check_changed: Callable[[str, bool], None],
        on_export_selected: Callable[[], None],
        on_export: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self.on_rename = on_rename
        self.on_toggle_visible = on_toggle_visible
        self.on_delete = on_delete
        self.on_browse_output = on_browse_output
        self.on_check_changed = on_check_changed
        self.on_export_selected = on_export_selected
        self.on_export = on_export
        self._updating_table = False
        self._checked_region_ids: set[str] = set()

        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel("区域列表"))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["选", "名称", "类型", "显示", "导出", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(240)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setMinimumSectionSize(48)
        self.table.horizontalHeader().setSectionResizeMode(COL_CHECKED, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_VISIBLE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_EXPORT_COUNT, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(COL_CHECKED, 48)
        self.table.setColumnWidth(COL_NAME, 190)
        self.table.setColumnWidth(COL_TYPE, 86)
        self.table.setColumnWidth(COL_VISIBLE, 64)
        self.table.setColumnWidth(COL_EXPORT_COUNT, 70)
        self.table.setColumnWidth(COL_STATUS, 86)
        self.table.itemSelectionChanged.connect(self._handle_select)
        self.table.itemChanged.connect(self._handle_item_changed)
        layout.addWidget(self.table, 1)

        form = QGridLayout()
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(2, 1)
        layout.addLayout(form)

        form.addWidget(QLabel("区域名称"), 0, 0, 1, 3)
        self.name_edit = QLineEdit()
        self.name_edit.setMinimumWidth(260)
        form.addWidget(self.name_edit, 1, 0, 1, 2)
        rename_button = QPushButton("重命名")
        rename_button.setMinimumWidth(92)
        rename_button.clicked.connect(self._rename)
        form.addWidget(rename_button, 1, 2)

        clear_button = QPushButton("取消选择")
        clear_button.setMinimumWidth(104)
        clear_button.clicked.connect(self.clear_selection)
        form.addWidget(clear_button, 2, 0)
        visible_button = QPushButton("显示/隐藏")
        visible_button.setMinimumWidth(104)
        visible_button.clicked.connect(self.on_toggle_visible)
        form.addWidget(visible_button, 2, 1)
        delete_button = QPushButton("删除区域")
        delete_button.setMinimumWidth(104)
        delete_button.clicked.connect(self.on_delete)
        form.addWidget(delete_button, 2, 2)

        layout.addWidget(self._build_export_settings())
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

    def set_regions(
        self,
        regions: list[Region],
        selected_region_id: str | None,
        preserve_checked: bool = True,
        checked_region_ids: set[str] | None = None,
    ) -> None:
        self._updating_table = True
        try:
            region_ids = {region.id for region in regions}
            if checked_region_ids is not None:
                self._checked_region_ids = set(checked_region_ids) & region_ids
            elif preserve_checked:
                self._checked_region_ids.intersection_update(region_ids)
            else:
                self._checked_region_ids.clear()

            self.table.setRowCount(0)
            inserted_ids: set[str] = set()
            for index, region in enumerate(regions, start=1):
                if region.id in inserted_ids:
                    continue
                inserted_ids.add(region.id)
                row = self.table.rowCount()
                self.table.insertRow(row)
                checked_item = QTableWidgetItem()
                checked_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                )
                checked_item.setCheckState(
                    Qt.CheckState.Checked
                    if region.id in self._checked_region_ids
                    else Qt.CheckState.Unchecked
                )
                checked_item.setData(Qt.ItemDataRole.UserRole, region.id)
                self.table.setItem(row, COL_CHECKED, checked_item)
                self.table.setItem(row, COL_NAME, _item(f"{index}. {region.display_name}", region.id))
                self.table.setItem(row, COL_TYPE, _center_item(region.shape_label, region.id))
                self.table.setItem(row, COL_VISIBLE, _center_item("是" if region.visible else "否", region.id))
                self.table.setItem(row, COL_EXPORT_COUNT, _center_item(str(region.export_count), region.id))
                self.table.setItem(row, COL_STATUS, _center_item("合法" if region.is_valid else "非法", region.id))

            if selected_region_id is not None:
                row = self._row_for_region(selected_region_id)
                if row is not None:
                    self.table.selectRow(row)
                    self.table.scrollToItem(self.table.item(row, COL_NAME))
                    region = next((item for item in regions if item.id == selected_region_id), None)
                    self.name_edit.setText(region.display_name if region else "")
                else:
                    self._clear_table_selection()
            else:
                self._clear_table_selection()
        finally:
            self._updating_table = False

    def clear_selection(self) -> None:
        self._clear_table_selection()
        self.on_select(None)

    def selected_region_id(self) -> str | None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.table.item(selected_rows[0].row(), COL_NAME)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def checked_region_ids(self) -> set[str]:
        return set(self._checked_region_ids)

    def set_checked_region_ids(self, region_ids: set[str]) -> None:
        existing_ids = {
            self.table.item(row, COL_NAME).data(Qt.ItemDataRole.UserRole)
            for row in range(self.table.rowCount())
            if self.table.item(row, COL_NAME) is not None
        }
        self._checked_region_ids = {region_id for region_id in region_ids if region_id in existing_ids}
        self._updating_table = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, COL_CHECKED)
                region_id = self._region_id_for_row(row)
                if item is not None and region_id is not None:
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if region_id in self._checked_region_ids
                        else Qt.CheckState.Unchecked
                    )
        finally:
            self._updating_table = False

    def set_output_dir(self, value: str) -> None:
        self.output_dir_edit.setText(value)

    def output_dir(self) -> str:
        return self.output_dir_edit.text().strip()

    def cutout_options(self) -> CutoutOptions:
        return CutoutOptions(
            feather_radius=self.feather_radius(),
            white_threshold=self.white_threshold_spin.value(),
            near_white_tolerance=self.near_white_tolerance_spin.value(),
            remove_small_components=self.remove_small_components_check.isChecked(),
            min_component_area=self.min_component_area_spin.value(),
            keep_largest_component=self.keep_largest_component_check.isChecked(),
        )

    def feather_radius(self) -> float:
        return max(0.0, float(self.feather_spin.value()))

    def set_progress(self, current: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(current)

    def _build_export_settings(self) -> QGroupBox:
        settings = QGroupBox("导出设置")
        settings.setMinimumWidth(500)
        layout = QVBoxLayout(settings)

        output_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setMinimumWidth(280)
        browse_button = QPushButton("选择")
        browse_button.setMinimumWidth(84)
        browse_button.clicked.connect(self.on_browse_output)
        output_layout.addWidget(self.output_dir_edit, 1)
        output_layout.addWidget(browse_button)
        form = QFormLayout()
        form.addRow("导出目录", output_layout)
        layout.addLayout(form)

        grid = QGridLayout()
        grid.setColumnMinimumWidth(0, 180)
        grid.setColumnMinimumWidth(1, 180)
        self.feather_spin = QDoubleSpinBox()
        self.feather_spin.setRange(0.0, 10.0)
        self.feather_spin.setDecimals(1)
        self.feather_spin.setSingleStep(0.5)
        self.feather_spin.setValue(1.5)
        grid.addWidget(QLabel("羽化半径 px"), 0, 0)
        grid.addWidget(self.feather_spin, 1, 0)

        self.white_threshold_spin = QSpinBox()
        self.white_threshold_spin.setRange(0, 255)
        self.white_threshold_spin.setValue(240)
        grid.addWidget(QLabel("白底阈值"), 0, 1)
        grid.addWidget(self.white_threshold_spin, 1, 1)

        self.near_white_tolerance_spin = QSpinBox()
        self.near_white_tolerance_spin.setRange(0, 255)
        self.near_white_tolerance_spin.setValue(15)
        grid.addWidget(QLabel("近白容差"), 2, 0)
        grid.addWidget(self.near_white_tolerance_spin, 3, 0)

        self.min_component_area_spin = QSpinBox()
        self.min_component_area_spin.setRange(1, 10000)
        self.min_component_area_spin.setValue(20)
        grid.addWidget(QLabel("最小噪点面积"), 2, 1)
        grid.addWidget(self.min_component_area_spin, 3, 1)
        layout.addLayout(grid)

        checks = QHBoxLayout()
        self.remove_small_components_check = QCheckBox("去除小噪点")
        self.remove_small_components_check.setChecked(True)
        self.keep_largest_component_check = QCheckBox("只保留最大连通域")
        self.remove_small_components_check.setMinimumWidth(150)
        self.keep_largest_component_check.setMinimumWidth(190)
        checks.addWidget(self.remove_small_components_check)
        checks.addWidget(self.keep_largest_component_check)
        layout.addLayout(checks)

        buttons = QHBoxLayout()
        export_selected_button = QPushButton("导出选中 SVG")
        export_selected_button.setMinimumWidth(170)
        export_selected_button.clicked.connect(self.on_export_selected)
        export_all_button = QPushButton("导出当前图片全部 SVG")
        export_all_button.setMinimumWidth(210)
        export_all_button.clicked.connect(self.on_export)
        buttons.addWidget(export_selected_button)
        buttons.addWidget(export_all_button)
        layout.addLayout(buttons)
        return settings

    def _handle_select(self) -> None:
        if self._updating_table:
            return
        region_id = self.selected_region_id()
        if region_id is None:
            self.name_edit.clear()
        self.on_select(region_id)

    def _handle_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() != COL_CHECKED:
            return
        region_id = item.data(Qt.ItemDataRole.UserRole)
        if not region_id:
            return
        region_id = str(region_id)
        checked = item.checkState() == Qt.CheckState.Checked
        if checked:
            self._checked_region_ids.add(region_id)
        else:
            self._checked_region_ids.discard(region_id)
        self.on_check_changed(region_id, checked)

    def _rename(self) -> None:
        self.on_rename(self.name_edit.text().strip())

    def _clear_table_selection(self) -> None:
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.name_edit.clear()

    def _row_for_region(self, region_id: str) -> int | None:
        for row in range(self.table.rowCount()):
            if self._region_id_for_row(row) == region_id:
                return row
        return None

    def _region_id_for_row(self, row: int) -> str | None:
        item = self.table.item(row, COL_NAME)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None


def _item(value: str, region_id: str) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setData(Qt.ItemDataRole.UserRole, region_id)
    return item


def _center_item(value: str, region_id: str) -> QTableWidgetItem:
    item = _item(value, region_id)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
