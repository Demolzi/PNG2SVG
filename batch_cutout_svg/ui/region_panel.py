from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from batch_cutout_svg.core.mask import (
    CUTOUT_MODE_BACKGROUND,
    CUTOUT_MODE_GRABCUT,
    CUTOUT_MODE_REGION,
    CutoutOptions,
    TARGET_FILTER_LARGEST,
    TARGET_FILTER_MAIN_WITH_NEIGHBORS,
    TARGET_FILTER_OFF,
)
from batch_cutout_svg.models import Region

COL_CHECKED = 0
COL_NAME = 1
COL_TYPE = 2
COL_VISIBLE = 3
COL_EXPORT_COUNT = 4
COL_STATUS = 5
DEFAULT_PRESET_KEY = "standard"


@dataclass(frozen=True)
class CutoutPreset:
    key: str
    label: str
    feather_radius: float
    edge_smooth_level: int
    white_threshold: int
    near_white_tolerance: int
    min_component_area: int
    remove_small_components: bool
    keep_largest_component: bool
    target_filter_mode: str
    main_neighbor_distance: int
    defringe_strength: int
    grabcut_iterations: int


CUTOUT_PRESETS = {
    "conservative": CutoutPreset(
        key="conservative",
        label="\u4fdd\u5b88\uff08\u5c11\u5220\uff09",
        feather_radius=0.4,
        edge_smooth_level=1,
        white_threshold=245,
        near_white_tolerance=10,
        min_component_area=10,
        remove_small_components=True,
        keep_largest_component=False,
        target_filter_mode=TARGET_FILTER_OFF,
        main_neighbor_distance=20,
        defringe_strength=1,
        grabcut_iterations=5,
    ),
    "standard": CutoutPreset(
        key="standard",
        label="\u6807\u51c6",
        feather_radius=0.7,
        edge_smooth_level=2,
        white_threshold=240,
        near_white_tolerance=15,
        min_component_area=30,
        remove_small_components=True,
        keep_largest_component=False,
        target_filter_mode=TARGET_FILTER_MAIN_WITH_NEIGHBORS,
        main_neighbor_distance=20,
        defringe_strength=1,
        grabcut_iterations=5,
    ),
    "strong": CutoutPreset(
        key="strong",
        label="\u5f3a\u529b\uff08\u591a\u53bb\u767d\u8fb9\uff09",
        feather_radius=1.0,
        edge_smooth_level=3,
        white_threshold=230,
        near_white_tolerance=28,
        min_component_area=35,
        remove_small_components=True,
        keep_largest_component=False,
        target_filter_mode=TARGET_FILTER_LARGEST,
        main_neighbor_distance=15,
        defringe_strength=2,
        grabcut_iterations=7,
    ),
}


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
        mode = self.cutout_mode_combo.currentData()
        mode_value = str(mode) if mode else CUTOUT_MODE_BACKGROUND
        if not self.advanced_options_group.isChecked():
            return cutout_options_for_preset(
                mode_value,
                str(self.quality_preset_combo.currentData() or DEFAULT_PRESET_KEY),
            )
        return CutoutOptions(
            mode=mode_value,
            feather_radius=self.feather_radius(),
            white_threshold=self.white_threshold_spin.value(),
            near_white_tolerance=self.near_white_tolerance_spin.value(),
            remove_small_components=self.remove_small_components_check.isChecked(),
            min_component_area=self.min_component_area_spin.value(),
            keep_largest_component=False,
            target_filter_mode=str(
                self.target_filter_mode_combo.currentData() or TARGET_FILTER_MAIN_WITH_NEIGHBORS
            ),
            main_neighbor_distance=self.main_neighbor_distance_spin.value(),
            edge_smooth_level=self.edge_smooth_level_spin.value(),
            edge_feather_radius=self.feather_radius(),
            decontaminate_edge=self.defringe_strength_spin.value() > 0,
            defringe_strength=self.defringe_strength_spin.value(),
            grabcut_iterations=self.grabcut_iterations_spin.value(),
        )

    def feather_radius(self) -> float:
        if hasattr(self, "advanced_options_group") and not self.advanced_options_group.isChecked():
            preset = _preset_for_key(str(self.quality_preset_combo.currentData() or DEFAULT_PRESET_KEY))
            return preset.feather_radius
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
        self.cutout_mode_combo = QComboBox()
        self.cutout_mode_combo.addItem(
            "\u767d\u5e95/\u6d45\u8272\u80cc\u666f\u53bb\u9664",
            CUTOUT_MODE_BACKGROUND,
        )
        self.cutout_mode_combo.addItem(
            "\u4ec5\u533a\u57df\u88c1\u526a",
            CUTOUT_MODE_REGION,
        )
        self.cutout_mode_combo.addItem(
            "GrabCut \u5206\u5272\uff08\u975e AI\uff09",
            CUTOUT_MODE_GRABCUT,
        )
        self.cutout_mode_combo.setToolTip(
            "\u767d\u5e95\u6a21\u5f0f\u4f1a\u81ea\u52a8\u53bb\u9664\u8fb9\u754c\u8fde\u901a\u7684\u6d45\u8272\u80cc\u666f\uff1b"
            "\u4ec5\u533a\u57df\u88c1\u526a\u53ea\u4fdd\u7559\u753b\u51fa\u7684\u533a\u57df\uff1b"
            "GrabCut \u7528 OpenCV \u4f20\u7edf\u5206\u5272\u7b97\u6cd5\u589e\u5f3a\u590d\u6742\u80cc\u666f\u3002"
        )
        self.quality_preset_combo = QComboBox()
        for preset in CUTOUT_PRESETS.values():
            self.quality_preset_combo.addItem(preset.label, preset.key)
        self.quality_preset_combo.setCurrentIndex(
            max(0, self.quality_preset_combo.findData(DEFAULT_PRESET_KEY))
        )
        self.quality_preset_combo.setToolTip(
            "\u4fdd\u5b88\u4f18\u5148\u4fdd\u7559\u7ec6\u8282\uff1b\u6807\u51c6\u9002\u5408\u591a\u6570\u767d\u5e95\u56fe\uff1b"
            "\u5f3a\u529b\u4f1a\u66f4\u79ef\u6781\u53bb\u9664\u6d45\u8272\u80cc\u666f\u548c\u767d\u8fb9\u3002"
        )
        self.quality_preset_combo.currentIndexChanged.connect(self._apply_selected_preset_to_controls)
        form.addRow("\u62a0\u56fe\u6a21\u5f0f", self.cutout_mode_combo)
        form.addRow("\u5904\u7406\u5f3a\u5ea6", self.quality_preset_combo)
        form.addRow("导出目录", output_layout)
        layout.addLayout(form)

        self.advanced_options_group = QGroupBox("\u9ad8\u7ea7\u53c2\u6570")
        self.advanced_options_group.setCheckable(True)
        self.advanced_options_group.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced_options_group)
        self.advanced_options_body = QWidget()
        advanced_body_layout = QVBoxLayout(self.advanced_options_body)
        advanced_body_layout.setContentsMargins(0, 0, 0, 0)

        advanced_form = QFormLayout()
        advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        advanced_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.feather_spin = QDoubleSpinBox()
        self.feather_spin.setRange(0.0, 10.0)
        self.feather_spin.setDecimals(1)
        self.feather_spin.setSingleStep(0.5)
        self.feather_spin.setValue(1.5)
        advanced_form.addRow("羽化半径 px", self.feather_spin)

        self.white_threshold_spin = QSpinBox()
        self.white_threshold_spin.setRange(0, 255)
        self.white_threshold_spin.setValue(240)
        advanced_form.addRow("白底阈值", self.white_threshold_spin)

        self.near_white_tolerance_spin = QSpinBox()
        self.near_white_tolerance_spin.setRange(0, 255)
        self.near_white_tolerance_spin.setValue(15)
        advanced_form.addRow("近白容差", self.near_white_tolerance_spin)

        self.min_component_area_spin = QSpinBox()
        self.min_component_area_spin.setRange(1, 10000)
        self.min_component_area_spin.setValue(20)
        advanced_form.addRow("最小噪点面积", self.min_component_area_spin)

        self.defringe_strength_spin = QSpinBox()
        self.defringe_strength_spin.setRange(0, 3)
        self.defringe_strength_spin.setValue(1)
        advanced_form.addRow("\u53bb\u767d\u8fb9\u5f3a\u5ea6", self.defringe_strength_spin)

        self.edge_smooth_level_spin = QSpinBox()
        self.edge_smooth_level_spin.setRange(0, 3)
        self.edge_smooth_level_spin.setValue(2)
        advanced_form.addRow("\u8fb9\u7f18\u5e73\u6ed1\u5f3a\u5ea6", self.edge_smooth_level_spin)

        self.target_filter_mode_combo = QComboBox()
        self.target_filter_mode_combo.addItem("\u5173\u95ed", TARGET_FILTER_OFF)
        self.target_filter_mode_combo.addItem(
            "\u6700\u5927\u4e3b\u4f53+\u8fd1\u90bb",
            TARGET_FILTER_MAIN_WITH_NEIGHBORS,
        )
        self.target_filter_mode_combo.addItem("\u53ea\u4fdd\u7559\u6700\u5927\u4e3b\u4f53", TARGET_FILTER_LARGEST)
        self.target_filter_mode_combo.setMinimumWidth(220)
        advanced_form.addRow("\u4e3b\u4f53\u7b5b\u9009\u6a21\u5f0f", self.target_filter_mode_combo)

        self.main_neighbor_distance_spin = QSpinBox()
        self.main_neighbor_distance_spin.setRange(0, 200)
        self.main_neighbor_distance_spin.setValue(20)
        advanced_form.addRow("\u4e3b\u4f53\u8fd1\u90bb\u8ddd\u79bb px", self.main_neighbor_distance_spin)

        self.grabcut_iterations_spin = QSpinBox()
        self.grabcut_iterations_spin.setRange(1, 10)
        self.grabcut_iterations_spin.setValue(5)
        advanced_form.addRow("GrabCut \u8fed\u4ee3\u6b21\u6570", self.grabcut_iterations_spin)
        advanced_body_layout.addLayout(advanced_form)

        checks = QHBoxLayout()
        self.remove_small_components_check = QCheckBox("去除小噪点")
        self.remove_small_components_check.setChecked(True)
        self.remove_small_components_check.setMinimumWidth(150)
        checks.addWidget(self.remove_small_components_check)
        advanced_body_layout.addLayout(checks)
        self.advanced_options_scroll = QScrollArea()
        self.advanced_options_scroll.setWidgetResizable(True)
        self.advanced_options_scroll.setMaximumHeight(260)
        self.advanced_options_scroll.setWidget(self.advanced_options_body)
        self.advanced_options_scroll.setVisible(False)
        self.advanced_options_group.toggled.connect(self.advanced_options_scroll.setVisible)
        advanced_layout.addWidget(self.advanced_options_scroll)
        layout.addWidget(self.advanced_options_group)
        self._apply_selected_preset_to_controls()

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

    def _apply_selected_preset_to_controls(self, _index: int | None = None) -> None:
        if not hasattr(self, "feather_spin"):
            return
        preset = _preset_for_key(str(self.quality_preset_combo.currentData() or DEFAULT_PRESET_KEY))
        self.feather_spin.setValue(preset.feather_radius)
        self.white_threshold_spin.setValue(preset.white_threshold)
        self.near_white_tolerance_spin.setValue(preset.near_white_tolerance)
        self.min_component_area_spin.setValue(preset.min_component_area)
        self.remove_small_components_check.setChecked(preset.remove_small_components)
        self.target_filter_mode_combo.setCurrentIndex(
            max(0, self.target_filter_mode_combo.findData(preset.target_filter_mode))
        )
        self.main_neighbor_distance_spin.setValue(preset.main_neighbor_distance)
        self.edge_smooth_level_spin.setValue(preset.edge_smooth_level)
        self.defringe_strength_spin.setValue(preset.defringe_strength)
        self.grabcut_iterations_spin.setValue(preset.grabcut_iterations)

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


def cutout_options_for_preset(mode: str, preset_key: str) -> CutoutOptions:
    preset = _preset_for_key(preset_key)
    return CutoutOptions(
        mode=mode,
        feather_radius=preset.feather_radius,
        white_threshold=preset.white_threshold,
        near_white_tolerance=preset.near_white_tolerance,
        remove_small_components=preset.remove_small_components,
        min_component_area=preset.min_component_area,
        keep_largest_component=preset.keep_largest_component,
        target_filter_mode=preset.target_filter_mode,
        main_neighbor_distance=preset.main_neighbor_distance,
        edge_smooth_level=preset.edge_smooth_level,
        edge_feather_radius=preset.feather_radius,
        decontaminate_edge=preset.defringe_strength > 0,
        defringe_strength=preset.defringe_strength,
        grabcut_iterations=preset.grabcut_iterations,
    )


def _preset_for_key(key: str) -> CutoutPreset:
    return CUTOUT_PRESETS.get(key, CUTOUT_PRESETS[DEFAULT_PRESET_KEY])
