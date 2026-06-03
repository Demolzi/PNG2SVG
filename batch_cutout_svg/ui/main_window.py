from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from batch_cutout_svg.core.exporter import export_all
from batch_cutout_svg.core.geometry import Point, validate_polygon
from batch_cutout_svg.core.image_loader import discover_images_in_folder, load_images
from batch_cutout_svg.models import ImageItem, Region
from batch_cutout_svg.models.region import next_region_id
from batch_cutout_svg.ui.canvas import (
    TOOL_ELLIPSE,
    TOOL_FREEHAND,
    TOOL_RECT,
    TOOL_SELECT,
    CanvasView,
)
from batch_cutout_svg.ui.image_list import ImageListPanel
from batch_cutout_svg.ui.region_panel import RegionPanel


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

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="导入图片", command=self.import_images).pack(side="left")
        ttk.Button(toolbar, text="导入文件夹", command=self.import_folder).pack(side="left", padx=(6, 16))

        for label, tool in (
            ("选择", TOOL_SELECT),
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
        self.canvas_view = CanvasView(panes, self.add_drawn_region, self.select_region)
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
        paths = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=(
                ("图片文件", "*.png *.jpg *.jpeg"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
            ),
        )
        if not paths:
            return
        self._load_paths([Path(path) for path in paths])

    def import_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择图片文件夹")
        if not folder:
            return
        paths = discover_images_in_folder(folder)
        if not paths:
            messagebox.showinfo("没有图片", "所选文件夹中没有 png/jpg/jpeg 图片。")
            return
        self._load_paths(paths)

    def _load_paths(self, paths: list[Path]) -> None:
        existing = {item.path.resolve() for item in self.images}
        new_paths = [path for path in paths if path.resolve() not in existing]
        if not new_paths:
            self.status_var.set("选中的图片已经在列表中。")
            return
        try:
            loaded = load_images(new_paths)
        except Exception as exc:  # noqa: BLE001 - show file-dialog errors to user.
            messagebox.showerror("导入失败", str(exc))
            return
        self.images.extend(loaded)
        self.image_list.set_images(self.images)
        if loaded:
            self.select_image(loaded[0].path)
            self.image_list.select_path(loaded[0].path)
        self.status_var.set(f"已导入 {len(loaded)} 张图片。")

    def select_image(self, path: Path) -> None:
        image = next((item for item in self.images if item.path == path), None)
        if image is None:
            return
        self.current_image = image
        self.selected_region_id = None
        self.canvas_view.set_image_item(image)
        self.region_panel.set_regions(image.regions, None)
        self._update_status()

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
        if self.current_image is None or self.selected_region_id is None:
            return
        self.current_image.regions = [
            region
            for region in self.current_image.regions
            if region.id != self.selected_region_id
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
        if self.current_image is None or self.selected_region_id is None:
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

    @staticmethod
    def _tool_label(tool: str) -> str:
        return {
            TOOL_SELECT: "选择",
            TOOL_RECT: "矩形",
            TOOL_ELLIPSE: "椭圆",
            TOOL_FREEHAND: "自由曲线",
        }.get(tool, tool)

