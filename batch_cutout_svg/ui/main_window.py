from __future__ import annotations

import traceback
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from batch_cutout_svg.core.exporter import ExportFailure, ExportSummary, export_all, export_region_as_svg
from batch_cutout_svg.core.geometry import Point, validate_polygon
from batch_cutout_svg.core.image_loader import discover_images_in_folder, load_images_with_report
from batch_cutout_svg.core.naming import build_region_export_path
from batch_cutout_svg.models import ImageItem, Region
from batch_cutout_svg.models.region import next_available_region_id
from batch_cutout_svg.ui.canvas import (
    TOOL_ELLIPSE,
    TOOL_FREEHAND,
    TOOL_HAND,
    TOOL_RECT,
    TOOL_SELECT,
    CanvasView,
)
from batch_cutout_svg.ui.image_list import ImageListPanel
from batch_cutout_svg.ui.region_panel import RegionPanel

IMPORT_DEBUG_LOG = Path("import_debug.log")
APP_ERRORS_LOG = Path("app_errors.log")
APP_ICON_PATH = "assets/feather_pen.ico"
IMAGE_FILTER = (
    "图片文件 (*.png *.PNG *.jpg *.JPG *.jpeg *.JPEG);;"
    "PNG (*.png *.PNG);;"
    "JPEG (*.jpg *.JPG *.jpeg *.JPEG);;"
    "所有文件 (*.*)"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("批量闭合区域抠图导出 SVG")
        self.setWindowIcon(QIcon(str(resource_path(APP_ICON_PATH))))
        self.resize(1440, 860)
        self.setMinimumSize(1240, 680)

        self.images: list[ImageItem] = []
        self.current_image: ImageItem | None = None
        self.selected_region_id: str | None = None
        self._checked_region_ids_by_image: dict[str, set[str]] = {}
        self._current_tool = TOOL_RECT

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self._build_toolbar(root)
        self._build_layout(root)
        self._set_status("导入图片后开始绘制区域。")

    def _build_toolbar(self, root: QVBoxLayout) -> None:
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        import_button = QPushButton("导入图片")
        import_button.clicked.connect(self.import_images)
        layout.addWidget(import_button)

        import_folder_button = QPushButton("导入文件夹")
        import_folder_button.clicked.connect(self.import_folder)
        layout.addWidget(import_folder_button)

        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for label, tool in (
            ("选择", TOOL_SELECT),
            ("手形", TOOL_HAND),
            ("矩形", TOOL_RECT),
            ("椭圆", TOOL_ELLIPSE),
            ("自由曲线", TOOL_FREEHAND),
        ):
            button = QRadioButton(label)
            button.setChecked(tool == self._current_tool)
            button.toggled.connect(lambda checked, value=tool: self._tool_changed(value) if checked else None)
            self.tool_group.addButton(button)
            layout.addWidget(button)

        fit_button = QPushButton("适应窗口")
        fit_button.clicked.connect(lambda: self.canvas_view.fit_to_window())
        layout.addWidget(fit_button)

        delete_button = QPushButton("删除当前图片全部区域")
        delete_button.clicked.connect(self.delete_current_image_regions)
        layout.addWidget(delete_button)

        layout.addStretch(1)
        export_all_button = QPushButton("导出所有文件")
        export_all_button.clicked.connect(self.export_all_regions)
        layout.addWidget(export_all_button)
        root.addWidget(toolbar)

    def _build_layout(self, root: QVBoxLayout) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.image_list = ImageListPanel(self.select_image)
        self.canvas_view = CanvasView(self.add_drawn_region, self.select_region, self.move_region)
        self.region_panel = RegionPanel(
            on_select=self.select_region,
            on_rename=self.rename_selected_region,
            on_toggle_visible=self.toggle_selected_region_visible,
            on_delete=self.delete_selected_region,
            on_browse_output=self.browse_output_dir,
            on_check_changed=self.region_check_changed,
            on_export_selected=self.export_checked_regions,
            on_export=self.export_current_image_regions,
        )

        splitter.addWidget(self.image_list)
        splitter.addWidget(self.canvas_view)
        splitter.addWidget(self.region_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        splitter.setSizes([300, 620, 520])
        root.addWidget(splitter, 1)

    def import_images(self) -> None:
        raw_paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            IMAGE_FILTER,
        )
        paths = _coerce_dialog_paths(raw_paths)
        self._log_import(f"dialog selected {len(paths)} path(s):\n{paths!r}")
        if paths:
            self._load_paths(paths)

    def import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        try:
            paths = discover_images_in_folder(folder)
            self._log_import(f"folder selected: {folder!r}\ndiscovered {len(paths)} image path(s)")
        except Exception as exc:  # noqa: BLE001 - show folder access errors to user.
            self._log_import(f"folder import failed: {folder!r}\n{exc}")
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        if not paths:
            QMessageBox.information(self, "没有图片", "所选文件夹中没有 png/jpg/jpeg 图片。")
            return
        self._load_paths(paths)

    def _load_paths(self, paths: list[Path]) -> None:
        self._log_import(f"_load_paths received {len(paths)} path(s):\n{paths!r}")
        existing = {self._path_key(item.path) for item in self.images}
        new_paths = [path for path in paths if self._path_key(path) not in existing]
        self._log_import(f"new paths after de-dupe {len(new_paths)}:\n{new_paths!r}")
        if not new_paths:
            self._set_status("选中的图片已经在列表中。")
            return

        result = load_images_with_report(new_paths)
        self._log_import(
            "loaded "
            f"{len(result.items)} image(s), failures {len(result.failures)}: "
            f"{[(failure.path, failure.reason) for failure in result.failures]!r}"
        )
        if not result.items:
            details = self._format_load_failures(result.failures)
            QMessageBox.critical(self, "导入失败", details or "没有可导入的图片。")
            self._set_status("图片导入失败。")
            return

        loaded = result.items
        self.images.extend(loaded)
        self.image_list.set_images(self.images)
        first_path = loaded[0].path
        self.image_list.select_path(first_path, notify=False)
        self._set_status("图片已读取，正在准备预览...")
        QTimer.singleShot(0, lambda path=first_path: self.select_image(path))

        if result.failures:
            details = self._format_load_failures(result.failures)
            QMessageBox.warning(
                self,
                "部分图片导入失败",
                f"成功导入 {len(loaded)} 张，失败 {len(result.failures)} 张。\n\n{details}",
            )
            self._set_status(f"已导入 {len(loaded)} 张图片，{len(result.failures)} 张失败。")

    def select_image(self, path: Path) -> None:
        self._log_import(f"select_image start: {path}")
        image = next((item for item in self.images if item.path == path), None)
        if image is None:
            self._log_import("select_image image not found")
            return
        self.current_image = image
        self.selected_region_id = None
        self.canvas_view.set_image_item(image)
        self.region_panel.set_regions(
            image.regions,
            None,
            checked_region_ids=self._checked_region_ids_for(image),
        )
        self._update_status()
        self._log_import("select_image done")

    def add_drawn_region(self, shape_type: str, data: dict, points: list[Point]) -> bool:
        if self.current_image is None:
            return False
        existing_polygons = [region.polygon_points for region in self.current_image.regions]
        validation = validate_polygon(
            points,
            self.current_image.width,
            self.current_image.height,
            existing_polygons=existing_polygons,
        )
        if not validation.is_valid:
            QMessageBox.warning(self, "区域非法", validation.error_message or "当前区域非法。")
            self._set_status(validation.error_message or "区域非法。")
            return False

        region_id = next_available_region_id(region.id for region in self.current_image.regions)
        region = Region(
            id=region_id,
            name=region_id,
            shape_type=shape_type,
            data=data,
            polygon_points=points,
            is_valid=True,
        )
        self.current_image.regions.append(region)
        self.selected_region_id = region.id
        self.canvas_view.set_selected_region(region.id)
        self.region_panel.set_regions(
            self.current_image.regions,
            region.id,
            checked_region_ids=self._checked_region_ids_for_current(),
        )
        self.image_list.set_images(self.images)
        self._update_status()
        return True

    def select_region(self, region_id: str | None) -> None:
        self.selected_region_id = region_id
        self.canvas_view.set_selected_region(region_id)
        if self.current_image is not None:
            self.region_panel.set_regions(
                self.current_image.regions,
                region_id,
                checked_region_ids=self._checked_region_ids_for_current(),
            )
        self._update_status()

    def region_check_changed(self, region_id: str, checked: bool) -> None:
        if self.current_image is None:
            return
        checked_ids = self._checked_region_ids_for_current()
        if checked:
            checked_ids.add(region_id)
        else:
            checked_ids.discard(region_id)

    def move_region(self, region_id: str, dx: float, dy: float) -> bool:
        if self.current_image is None:
            return False
        region = next((item for item in self.current_image.regions if item.id == region_id), None)
        if region is None:
            return False
        moved_points = _translate_points(region.polygon_points, dx, dy)
        existing_polygons = [
            item.polygon_points
            for item in self.current_image.regions
            if item.id != region_id
        ]
        validation = validate_polygon(
            moved_points,
            self.current_image.width,
            self.current_image.height,
            existing_polygons=existing_polygons,
        )
        if not validation.is_valid:
            self._set_status(validation.error_message or "区域移动后非法。")
            return False

        _translate_region(region, dx, dy, moved_points=moved_points)
        region.is_valid = True
        region.error_message = None
        self.selected_region_id = region.id
        self._update_status()
        return True

    def rename_selected_region(self, name: str) -> None:
        region = self._selected_region()
        if region is None:
            return
        region.name = name.strip() or region.id
        self._refresh_regions()

    def toggle_selected_region_visible(self) -> None:
        region = self._selected_region()
        if region is None:
            return
        region.visible = not region.visible
        self._refresh_regions()

    def delete_selected_region(self) -> None:
        if self.current_image is None:
            return
        region_id = self.selected_region_id or self.region_panel.selected_region_id()
        if region_id is None:
            self._set_status("请先选择要删除的区域。")
            return
        checked_ids = set(self._checked_region_ids_for_current())
        self.current_image.regions = [
            region
            for region in self.current_image.regions
            if region.id != region_id
        ]
        self._set_checked_region_ids_for_current(checked_ids - {region_id})
        self.selected_region_id = None
        self._refresh_regions()

    def delete_current_image_regions(self) -> None:
        if self.current_image is None:
            self._set_status("请先选择一张图片。")
            return
        if not self.current_image.regions:
            self._set_status("当前图片没有可删除的区域。")
            return
        self.current_image.regions.clear()
        self._set_checked_region_ids_for_current(set())
        self.selected_region_id = None
        self._refresh_regions()
        self._set_status(f"已删除当前图片 {self.current_image.file_name} 的全部区域。")

    def browse_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if folder:
            self.region_panel.set_output_dir(folder)

    def export_all_regions(self) -> None:
        if not self.images:
            QMessageBox.information(self, "没有图片", "请先导入图片并绘制区域。")
            return
        total_regions = sum(len(image.regions) for image in self.images)
        if total_regions == 0:
            QMessageBox.information(self, "没有区域", "请先绘制至少一个闭合区域。")
            return
        output_dir = self._ensure_output_dir()
        if output_dir is None:
            return

        def update_progress(done: int, total: int) -> None:
            self.region_panel.set_progress(done, total)
            self._set_status(f"正在导出 {done}/{total} ...")
            QApplication.processEvents()

        summary = export_all(
            self.images,
            output_dir,
            feather_radius=self.region_panel.feather_radius(),
            cutout_options=self.region_panel.cutout_options(),
            progress_callback=update_progress,
        )
        self._restore_editing_state_after_export()
        self._show_export_summary(summary, "所有文件导出完成")

    def export_current_image_regions(self) -> None:
        if self.current_image is None:
            QMessageBox.information(self, "没有图片", "请先导入并选择一张图片。")
            return
        current_regions = list(enumerate(self.current_image.regions, start=1))
        if not current_regions:
            QMessageBox.information(self, "没有区域", "当前图片没有可导出的区域。")
            return
        output_dir = self._ensure_output_dir()
        if output_dir is None:
            return

        summary = ExportSummary()
        total = len(current_regions)
        cutout_options = self.region_panel.cutout_options()
        feather_radius = self.region_panel.feather_radius()
        for done, (index, region) in enumerate(current_regions, start=1):
            try:
                if not region.is_valid:
                    raise ValueError(region.error_message or "区域非法。")
                output_path = build_region_export_path(output_dir, self.current_image, region, index)
                exported = export_region_as_svg(
                    self.current_image,
                    region,
                    output_path,
                    feather_radius=feather_radius,
                    cutout_options=cutout_options,
                )
                summary.exported_paths.append(exported)
                region.export_count += 1
            except Exception as exc:  # noqa: BLE001 - current-image batch export keeps going.
                summary.failures.append(
                    ExportFailure(
                        image_name=self.current_image.file_name,
                        region_name=region.display_name,
                        reason=str(exc),
                    )
                )
            self.region_panel.set_progress(done, total)
            self._set_status(f"正在导出当前图片区域 {done}/{total} ...")
            QApplication.processEvents()

        if summary.success_count:
            self.current_image.exported = True
        self._restore_editing_state_after_export()
        self._show_export_summary(summary, "当前图片全部区域导出完成")

    def export_checked_regions(self) -> None:
        if self.current_image is None:
            QMessageBox.information(self, "没有图片", "请先导入图片并选择要导出的区域。")
            return
        checked_ids = self._checked_region_ids_for_current()
        selected_regions = [
            (index, region)
            for index, region in enumerate(self.current_image.regions, start=1)
            if region.id in checked_ids
        ]
        if not selected_regions:
            QMessageBox.information(self, "没有选中区域", "请先在右侧区域列表中勾选要导出的区域。")
            return
        output_dir = self._ensure_output_dir()
        if output_dir is None:
            return

        summary = ExportSummary()
        total = len(selected_regions)
        cutout_options = self.region_panel.cutout_options()
        feather_radius = self.region_panel.feather_radius()
        for done, (index, region) in enumerate(selected_regions, start=1):
            try:
                if not region.is_valid:
                    raise ValueError(region.error_message or "区域非法。")
                output_path = build_region_export_path(output_dir, self.current_image, region, index)
                exported = export_region_as_svg(
                    self.current_image,
                    region,
                    output_path,
                    feather_radius=feather_radius,
                    cutout_options=cutout_options,
                )
                summary.exported_paths.append(exported)
                region.export_count += 1
            except Exception as exc:  # noqa: BLE001 - selected batch export keeps going.
                summary.failures.append(
                    ExportFailure(
                        image_name=self.current_image.file_name,
                        region_name=region.display_name,
                        reason=str(exc),
                    )
                )
            self.region_panel.set_progress(done, total)
            self._set_status(f"正在导出选中区域 {done}/{total} ...")
            QApplication.processEvents()

        if summary.success_count:
            self.current_image.exported = True
        self._restore_editing_state_after_export()
        self._show_export_summary(summary, "选中区域导出完成")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override.
        if event.key() == Qt.Key.Key_Escape:
            self.select_region(None)
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_export_summary(self, summary: ExportSummary, success_title: str) -> None:
        if summary.failures:
            details = "\n".join(
                f"{failure.image_name} / {failure.region_name}: {failure.reason}"
                for failure in summary.failures[:10]
            )
            if len(summary.failures) > 10:
                details += f"\n... 还有 {len(summary.failures) - 10} 项失败"
            QMessageBox.warning(
                self,
                "导出完成但有失败项",
                f"成功 {summary.success_count} 个，失败 {summary.failure_count} 个。\n\n{details}",
            )
        else:
            QMessageBox.information(self, success_title, f"成功导出 {summary.success_count} 个 SVG。")

    def _ensure_output_dir(self) -> str | None:
        output_dir = self.region_panel.output_dir()
        if output_dir:
            return output_dir
        folder = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not folder:
            return None
        self.region_panel.set_output_dir(folder)
        return folder

    def _tool_changed(self, tool: str) -> None:
        self._current_tool = tool
        self.canvas_view.set_tool(tool)
        self._set_status(f"当前工具: {self._tool_label(tool)}")

    def _selected_region(self) -> Region | None:
        if self.current_image is None:
            return None
        if self.selected_region_id is None:
            self.selected_region_id = self.region_panel.selected_region_id()
        if self.selected_region_id is None:
            return None
        return next(
            (region for region in self.current_image.regions if region.id == self.selected_region_id),
            None,
        )

    def _refresh_regions(self) -> None:
        if self.current_image is None:
            return
        self.canvas_view.set_selected_region(self.selected_region_id)
        self.region_panel.set_regions(
            self.current_image.regions,
            self.selected_region_id,
            checked_region_ids=self._checked_region_ids_for_current(),
        )
        self.image_list.set_images(self.images)
        self.canvas_view.redraw()
        self._update_status()

    def _restore_editing_state_after_export(self) -> None:
        current_image = self.current_image
        selected_region_id = self.selected_region_id
        self.image_list.set_images(self.images)
        if current_image is None:
            self._update_status()
            return

        self.current_image = current_image
        self.selected_region_id = (
            selected_region_id
            if any(region.id == selected_region_id for region in current_image.regions)
            else None
        )
        self.image_list.select_path(current_image.path, notify=False)
        if self.canvas_view.image_item is not current_image:
            self.canvas_view.set_image_item(current_image)
        self.canvas_view.set_selected_region(self.selected_region_id)
        self.region_panel.set_regions(
            current_image.regions,
            self.selected_region_id,
            checked_region_ids=self._checked_region_ids_for_current(),
        )
        QApplication.processEvents()
        self._update_status()

    def _checked_region_ids_for_current(self) -> set[str]:
        if self.current_image is None:
            return set()
        return self._checked_region_ids_for(self.current_image)

    def _checked_region_ids_for(self, image: ImageItem) -> set[str]:
        return self._checked_region_ids_by_image.setdefault(self._path_key(image.path), set())

    def _set_checked_region_ids_for_current(self, region_ids: set[str]) -> None:
        if self.current_image is None:
            return
        existing_ids = {region.id for region in self.current_image.regions}
        self._checked_region_ids_by_image[self._path_key(self.current_image.path)] = region_ids & existing_ids

    def _update_status(self) -> None:
        if self.current_image is None:
            self._set_status("导入图片后开始绘制区域。")
            return
        region = self._selected_region()
        selected = f"，选中 {region.display_name}" if region else ""
        self._set_status(
            f"当前图片: {self.current_image.file_name}，"
            f"{self.current_image.width}x{self.current_image.height}，"
            f"区域 {len(self.current_image.regions)} 个{selected}"
        )

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    @staticmethod
    def _log_import(message: str) -> None:
        _append_log(IMPORT_DEBUG_LOG, message)

    @staticmethod
    def _tool_label(tool: str) -> str:
        return {
            TOOL_SELECT: "选择",
            TOOL_HAND: "手形",
            TOOL_RECT: "矩形",
            TOOL_ELLIPSE: "椭圆",
            TOOL_FREEHAND: "自由曲线",
        }.get(tool, tool)

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).lower()
        except OSError:
            return str(path.absolute()).lower()

    @staticmethod
    def _format_load_failures(failures: list) -> str:
        if not failures:
            return ""
        lines = [
            f"{failure.path}: {failure.reason}"
            for failure in failures[:8]
        ]
        if len(failures) > 8:
            lines.append(f"... 还有 {len(failures) - 8} 项失败")
        return "\n".join(lines)


def _coerce_dialog_paths(
    raw_paths: object,
    splitlist: Callable[[str], tuple[str, ...]] | None = None,
) -> list[Path]:
    if not raw_paths:
        return []
    if isinstance(raw_paths, str):
        values = splitlist(raw_paths) if splitlist is not None else (raw_paths,)
    else:
        values = raw_paths
    return [
        _absolute_path(Path(str(value)))
        for value in values
        if str(value).strip()
    ]


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    try:
        return expanded.resolve(strict=False)
    except OSError:
        return expanded.absolute()


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base_path / relative_path


def _translate_region(
    region: Region,
    dx: float,
    dy: float,
    moved_points: list[Point] | None = None,
) -> None:
    region.polygon_points = moved_points if moved_points is not None else _translate_points(
        region.polygon_points,
        dx,
        dy,
    )
    _translate_numeric_field(region.data, "x", dx)
    _translate_numeric_field(region.data, "cx", dx)
    _translate_numeric_field(region.data, "y", dy)
    _translate_numeric_field(region.data, "cy", dy)
    points = region.data.get("points")
    if points is not None:
        try:
            region.data["points"] = [(float(x) + dx, float(y) + dy) for x, y in points]
        except (TypeError, ValueError):
            pass


def _translate_points(points: list[Point], dx: float, dy: float) -> list[Point]:
    return [(x + dx, y + dy) for x, y in points]


def _translate_numeric_field(data: dict, key: str, delta: float) -> None:
    value = data.get(key)
    if isinstance(value, (int, float)):
        data[key] = value + delta


def log_unhandled_exception(exc_type: type[BaseException], exc: BaseException, tb) -> None:
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    _append_log(APP_ERRORS_LOG, f"Qt callback exception:\n{details}")
    QMessageBox.critical(
        None,
        "程序错误",
        f"界面回调发生异常，详情已写入 {APP_ERRORS_LOG}。\n\n{exc}",
    )


def _append_log(path: Path, message: str) -> None:
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n\n")
    except OSError:
        pass
