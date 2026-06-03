from __future__ import annotations

import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from batch_cutout_svg.core.exporter import export_all
from batch_cutout_svg.core.geometry import Point, validate_polygon
from batch_cutout_svg.core.image_loader import discover_images_in_folder, load_images_with_report
from batch_cutout_svg.models import ImageItem, Region
from batch_cutout_svg.models.region import next_region_id
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
IMAGE_FILETYPES = (
    ("图片文件", ("*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG")),
    ("PNG", ("*.png", "*.PNG")),
    ("JPEG", ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG")),
    ("所有文件", "*.*"),
)


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("批量闭合区域抠图导出 SVG")
        self.geometry("1280x800")
        self.minsize(980, 640)

        self.images: list[ImageItem] = []
        self.current_image: ImageItem | None = None
        self.selected_region_id: str | None = None
        self.status_var = tk.StringVar(value="导入图片后开始绘制区域。")
        self.tool_var = tk.StringVar(value=TOOL_RECT)

        self._build_toolbar()
        self._build_layout()
        self._build_statusbar()
        self.bind("<Escape>", lambda _event: self.select_region(None))

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="导入图片", command=self.import_images).pack(side="left")
        ttk.Button(toolbar, text="导入文件夹", command=self.import_folder).pack(side="left", padx=(6, 16))

        for label, tool in (
            ("选择", TOOL_SELECT),
            ("手形", TOOL_HAND),
            ("矩形", TOOL_RECT),
            ("椭圆", TOOL_ELLIPSE),
            ("自由曲线", TOOL_FREEHAND),
        ):
            ttk.Radiobutton(
                toolbar,
                text=label,
                value=tool,
                variable=self.tool_var,
                command=self._tool_changed,
            ).pack(side="left", padx=2)

        ttk.Button(toolbar, text="适应窗口", command=lambda: self.canvas_view.fit_to_window()).pack(
            side="left",
            padx=(16, 6),
        )
        ttk.Button(toolbar, text="删除区域", command=self.delete_selected_region).pack(side="left")
        ttk.Button(toolbar, text="导出全部", command=self.export_all_regions).pack(side="right")

    def _build_layout(self) -> None:
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)

        self.image_list = ImageListPanel(panes, self.select_image)
        self.canvas_view = CanvasView(panes, self.add_drawn_region, self.select_region, self.move_region)
        self.region_panel = RegionPanel(
            panes,
            on_select=self.select_region,
            on_rename=self.rename_selected_region,
            on_toggle_visible=self.toggle_selected_region_visible,
            on_delete=self.delete_selected_region,
            on_browse_output=self.browse_output_dir,
            on_export=self.export_all_regions,
        )

        panes.add(self.image_list, weight=1)
        panes.add(self.canvas_view, weight=5)
        panes.add(self.region_panel, weight=2)

    def _build_statusbar(self) -> None:
        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(8, 4))
        status.pack(side="bottom", fill="x")

    def import_images(self) -> None:
        raw_paths = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=IMAGE_FILETYPES,
        )
        paths = _coerce_dialog_paths(raw_paths, self.tk.splitlist)
        self._log_import(f"dialog selected {len(paths)} path(s):\n{paths!r}")
        if not paths:
            return
        self._load_paths(paths)

    def import_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择图片文件夹")
        if not folder:
            return
        try:
            paths = discover_images_in_folder(folder)
            self._log_import(f"folder selected: {folder!r}\ndiscovered {len(paths)} image path(s)")
        except Exception as exc:  # noqa: BLE001 - show folder access errors to user.
            self._log_import(f"folder import failed: {folder!r}\n{exc}")
            messagebox.showerror("导入失败", str(exc))
            return
        if not paths:
            messagebox.showinfo("没有图片", "所选文件夹中没有 png/jpg/jpeg 图片。")
            return
        self._load_paths(paths)

    def _load_paths(self, paths: list[Path]) -> None:
        self._log_import(f"_load_paths received {len(paths)} path(s):\n{paths!r}")
        existing = {self._path_key(item.path) for item in self.images}
        new_paths = [path for path in paths if self._path_key(path) not in existing]
        self._log_import(f"new paths after de-dupe {len(new_paths)}:\n{new_paths!r}")
        if not new_paths:
            self.status_var.set("选中的图片已经在列表中。")
            return
        result = load_images_with_report(new_paths)
        self._log_import(
            "loaded "
            f"{len(result.items)} image(s), failures {len(result.failures)}: "
            f"{[(failure.path, failure.reason) for failure in result.failures]!r}"
        )
        if not result.items:
            details = self._format_load_failures(result.failures)
            messagebox.showerror("导入失败", details or "没有可导入的图片。")
            self.status_var.set("图片导入失败。")
            return
        loaded = result.items
        self._log_import("before extend images")
        self.images.extend(loaded)
        self._log_import("after extend images")
        self._log_import("before image_list.set_images")
        self.image_list.set_images(self.images)
        self._log_import("after image_list.set_images")
        if loaded:
            first_path = loaded[0].path
            self._log_import(f"before image_list.select_path: {first_path}")
            self.image_list.select_path(first_path, notify=False)
            self._log_import("after image_list.select_path")
            self.status_var.set("图片已读取，正在准备预览...")
            self._log_import(f"before delayed select_image schedule: {first_path}")
            self.after(10, lambda path=first_path: self.select_image(path))
            self._log_import("after delayed select_image schedule")
        if result.failures:
            details = self._format_load_failures(result.failures)
            messagebox.showwarning(
                "部分图片导入失败",
                f"成功导入 {len(loaded)} 张，失败 {len(result.failures)} 张。\n\n{details}",
            )
            self.status_var.set(f"已导入 {len(loaded)} 张图片，{len(result.failures)} 张失败。")
        elif not loaded:
            self.status_var.set(f"已导入 {len(loaded)} 张图片。")

    def select_image(self, path: Path) -> None:
        self._log_import(f"select_image start: {path}")
        image = next((item for item in self.images if item.path == path), None)
        if image is None:
            self._log_import("select_image image not found")
            return
        self.current_image = image
        self.selected_region_id = None
        self._log_import("before canvas_view.set_image_item")
        self.canvas_view.set_image_item(image)
        self._log_import("after canvas_view.set_image_item")
        self._log_import("before region_panel.set_regions")
        self.region_panel.set_regions(image.regions, None)
        self._log_import("after region_panel.set_regions")
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
            messagebox.showwarning("区域非法", validation.error_message or "当前区域非法。")
            self.status_var.set(validation.error_message or "区域非法。")
            return False

        region_id = next_region_id(len(self.current_image.regions))
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
        self.region_panel.set_regions(self.current_image.regions, region.id)
        self.image_list.set_images(self.images)
        self._update_status()
        return True

    def select_region(self, region_id: str | None) -> None:
        self.selected_region_id = region_id
        self.canvas_view.set_selected_region(region_id)
        if self.current_image is not None:
            self.region_panel.set_regions(self.current_image.regions, region_id)
        self._update_status()

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
            self.status_var.set(validation.error_message or "区域移动后非法。")
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
            self.status_var.set("请先选择要删除的区域。")
            return
        self.current_image.regions = [
            region
            for region in self.current_image.regions
            if region.id != region_id
        ]
        self.selected_region_id = None
        self._refresh_regions()

    def browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="选择导出目录")
        if folder:
            self.region_panel.set_output_dir(folder)

    def export_all_regions(self) -> None:
        if not self.images:
            messagebox.showinfo("没有图片", "请先导入图片并绘制区域。")
            return
        total_regions = sum(len(image.regions) for image in self.images)
        if total_regions == 0:
            messagebox.showinfo("没有区域", "请先绘制至少一个闭合区域。")
            return
        output_dir = self.region_panel.output_dir()
        if not output_dir:
            folder = filedialog.askdirectory(title="选择导出目录")
            if not folder:
                return
            output_dir = folder
            self.region_panel.set_output_dir(folder)

        def update_progress(done: int, total: int) -> None:
            self.region_panel.set_progress(done, total)
            self.status_var.set(f"正在导出 {done}/{total} ...")
            self.update_idletasks()

        summary = export_all(
            self.images,
            output_dir,
            feather_radius=self.region_panel.feather_radius(),
            cutout_options=self.region_panel.cutout_options(),
            progress_callback=update_progress,
        )
        self.image_list.set_images(self.images)
        self._update_status()
        if summary.failures:
            details = "\n".join(
                f"{failure.image_name} / {failure.region_name}: {failure.reason}"
                for failure in summary.failures[:10]
            )
            if len(summary.failures) > 10:
                details += f"\n... 还有 {len(summary.failures) - 10} 项失败"
            messagebox.showwarning(
                "导出完成但有失败项",
                f"成功 {summary.success_count} 个，失败 {summary.failure_count} 个。\n\n{details}",
            )
        else:
            messagebox.showinfo("导出完成", f"成功导出 {summary.success_count} 个 SVG。")

    def _tool_changed(self) -> None:
        self.canvas_view.set_tool(self.tool_var.get())
        self.status_var.set(f"当前工具: {self._tool_label(self.tool_var.get())}")

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
        self.region_panel.set_regions(self.current_image.regions, self.selected_region_id)
        self.image_list.set_images(self.images)
        self.canvas_view.redraw()
        self._update_status()

    def _update_status(self) -> None:
        if self.current_image is None:
            self.status_var.set("导入图片后开始绘制区域。")
            return
        region = self._selected_region()
        selected = f"，选中 {region.display_name}" if region else ""
        self.status_var.set(
            f"当前图片: {self.current_image.file_name}，"
            f"{self.current_image.width}x{self.current_image.height}，"
            f"区域 {len(self.current_image.regions)} 个{selected}"
        )

    def report_callback_exception(self, exc_type: type[BaseException], exc: BaseException, tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        _append_log(APP_ERRORS_LOG, f"Tk callback exception:\n{details}")
        try:
            messagebox.showerror(
                "程序错误",
                f"界面回调发生异常，详情已写入 {APP_ERRORS_LOG}。\n\n{exc}",
            )
        except tk.TclError:
            pass

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
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser().absolute()


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


def _append_log(path: Path, message: str) -> None:
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n\n")
    except OSError:
        pass

