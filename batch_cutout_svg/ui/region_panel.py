from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from batch_cutout_svg.core.mask import CutoutOptions
from batch_cutout_svg.models import Region

CHECKED_MARK = "☑"
UNCHECKED_MARK = "☐"


class RegionPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        on_select: Callable[[str | None], None],
        on_rename: Callable[[str], None],
        on_toggle_visible: Callable[[], None],
        on_delete: Callable[[], None],
        on_browse_output: Callable[[], None],
        on_check_changed: Callable[[str, bool], None],
        on_export_selected: Callable[[], None],
        on_export: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.on_select = on_select
        self.on_rename = on_rename
        self.on_toggle_visible = on_toggle_visible
        self.on_delete = on_delete
        self.on_browse_output = on_browse_output
        self.on_check_changed = on_check_changed
        self.on_export_selected = on_export_selected
        self.on_export = on_export
        self._updating_tree = False
        self._suppress_selection_callback = False
        self._checked_region_ids: set[str] = set()
        self._checkbox_click_region_id: str | None = None

        self.name_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.feather_var = tk.DoubleVar(value=1.5)
        self.white_threshold_var = tk.IntVar(value=240)
        self.near_white_tolerance_var = tk.IntVar(value=15)
        self.remove_small_components_var = tk.BooleanVar(value=True)
        self.min_component_area_var = tk.IntVar(value=20)
        self.keep_largest_component_var = tk.BooleanVar(value=False)

        ttk.Label(self, text="区域列表").pack(anchor="w", padx=8, pady=(8, 4))
        columns = ("checked", "name", "type", "visible", "status")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=12,
        )
        for column, label, width in (
            ("checked", "选", 38),
            ("name", "名称", 102),
            ("type", "类型", 72),
            ("visible", "显示", 48),
            ("status", "状态", 76),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="center", stretch=column == "name")
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.bind("<Button-1>", self._handle_click)
        self.tree.bind("<ButtonRelease-1>", self._handle_release)
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)

        form = ttk.Frame(self)
        form.pack(fill="x", padx=8, pady=8)
        ttk.Label(form, text="区域名称").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(form, textvariable=self.name_var)
        name_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        form.columnconfigure(0, weight=1)
        ttk.Button(form, text="重命名", command=self._rename).grid(row=1, column=2, padx=(6, 0), sticky="ew")
        ttk.Button(form, text="取消选择", command=self.clear_selection).grid(row=2, column=0, sticky="ew")
        ttk.Button(form, text="显示/隐藏", command=self.on_toggle_visible).grid(row=2, column=1, padx=(6, 0), sticky="ew")
        ttk.Button(form, text="删除区域", command=self.on_delete).grid(row=2, column=2, padx=(6, 0), sticky="ew")

        settings = ttk.LabelFrame(self, text="导出设置")
        settings.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(settings, text="导出目录").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Entry(settings, textvariable=self.output_dir_var).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(8, 4),
            pady=(0, 8),
        )
        ttk.Button(settings, text="选择", command=self.on_browse_output).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(4, 8),
            pady=(0, 8),
        )
        ttk.Label(settings, text="羽化半径 px").grid(row=2, column=0, sticky="w", padx=8)
        ttk.Spinbox(
            settings,
            from_=0.0,
            to=10.0,
            increment=0.5,
            textvariable=self.feather_var,
            width=8,
        ).grid(row=3, column=0, sticky="w", padx=8, pady=(2, 8))
        ttk.Label(settings, text="白底阈值").grid(row=2, column=1, sticky="w", padx=8)
        ttk.Spinbox(
            settings,
            from_=0,
            to=255,
            increment=1,
            textvariable=self.white_threshold_var,
            width=8,
        ).grid(row=3, column=1, sticky="w", padx=8, pady=(2, 8))
        ttk.Label(settings, text="近白容差").grid(row=4, column=0, sticky="w", padx=8)
        ttk.Spinbox(
            settings,
            from_=0,
            to=255,
            increment=1,
            textvariable=self.near_white_tolerance_var,
            width=8,
        ).grid(row=5, column=0, sticky="w", padx=8, pady=(2, 8))
        ttk.Label(settings, text="最小噪点面积").grid(row=4, column=1, sticky="w", padx=8)
        ttk.Spinbox(
            settings,
            from_=1,
            to=10000,
            increment=1,
            textvariable=self.min_component_area_var,
            width=8,
        ).grid(row=5, column=1, sticky="w", padx=8, pady=(2, 8))
        ttk.Checkbutton(
            settings,
            text="去除小噪点",
            variable=self.remove_small_components_var,
        ).grid(row=6, column=0, sticky="w", padx=8, pady=(0, 4))
        ttk.Checkbutton(
            settings,
            text="只保留最大连通域",
            variable=self.keep_largest_component_var,
        ).grid(row=6, column=1, sticky="w", padx=8, pady=(0, 4))
        ttk.Button(settings, text="导出选中 SVG", command=self.on_export_selected).grid(
            row=7,
            column=0,
            sticky="ew",
            padx=8,
            pady=(2, 8),
        )
        ttk.Button(settings, text="导出全部 SVG", command=self.on_export).grid(
            row=7,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=(2, 8),
        )
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

    def set_regions(
        self,
        regions: list[Region],
        selected_region_id: str | None,
        preserve_checked: bool = True,
        checked_region_ids: set[str] | None = None,
    ) -> None:
        self._updating_tree = True
        self._suppress_selection_callback = True
        try:
            region_ids = {region.id for region in regions}
            if checked_region_ids is not None:
                self._checked_region_ids = set(checked_region_ids) & region_ids
            elif preserve_checked:
                self._checked_region_ids.intersection_update(region_ids)
            else:
                self._checked_region_ids.clear()
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            for index, region in enumerate(regions, start=1):
                self.tree.insert(
                    "",
                    "end",
                    iid=region.id,
                    values=(
                        self._check_mark(region.id),
                        f"{index}. {region.display_name}",
                        region.shape_label,
                        "是" if region.visible else "否",
                        "合法" if region.is_valid else "非法",
                    ),
                )
            if selected_region_id and selected_region_id in self.tree.get_children():
                self.tree.selection_set(selected_region_id)
                self.tree.focus(selected_region_id)
                region = next((item for item in regions if item.id == selected_region_id), None)
                self.name_var.set(region.display_name if region else "")
            else:
                self.tree.selection_remove(self.tree.selection())
                self.tree.focus("")
                self.name_var.set("")
        finally:
            self._updating_tree = False
            self.after_idle(self._clear_selection_suppression)

    def clear_selection(self) -> None:
        self.tree.selection_remove(self.tree.selection())
        self.tree.focus("")
        self.name_var.set("")
        self.on_select(None)

    def selected_region_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def checked_region_ids(self) -> set[str]:
        return set(self._checked_region_ids)

    def set_checked_region_ids(self, region_ids: set[str]) -> None:
        existing_ids = set(self.tree.get_children())
        self._checked_region_ids = {region_id for region_id in region_ids if region_id in existing_ids}
        for iid in self.tree.get_children():
            self.tree.set(iid, "checked", self._check_mark(iid))

    def set_output_dir(self, value: str) -> None:
        self.output_dir_var.set(value)

    def output_dir(self) -> str:
        return self.output_dir_var.get().strip()

    def cutout_options(self) -> CutoutOptions:
        return CutoutOptions(
            feather_radius=self.feather_radius(),
            white_threshold=self._int_value(self.white_threshold_var, 240, 0, 255),
            near_white_tolerance=self._int_value(self.near_white_tolerance_var, 15, 0, 255),
            remove_small_components=bool(self.remove_small_components_var.get()),
            min_component_area=self._int_value(self.min_component_area_var, 20, 1, 10000),
            keep_largest_component=bool(self.keep_largest_component_var.get()),
        )

    def feather_radius(self) -> float:
        try:
            return max(0.0, float(self.feather_var.get()))
        except (tk.TclError, ValueError):
            return 1.5

    def set_progress(self, current: int, total: int) -> None:
        self.progress.configure(maximum=max(1, total), value=current)

    def _handle_click(self, event: tk.Event) -> str | None:
        region = self.tree.identify_region(event.x, event.y)
        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if region not in {"cell", "tree"}:
            return None
        if not row_id:
            self.clear_selection()
            return "break"
        if column_id == "#1":
            self._toggle_checked(row_id)
            self._checkbox_click_region_id = row_id
            return "break"
        return None

    def _handle_release(self, event: tk.Event) -> None:
        if self._updating_tree or self._suppress_selection_callback:
            return
        row_id = self.tree.identify_row(event.y)
        if self._checkbox_click_region_id is not None:
            self._checkbox_click_region_id = None
            return
        if row_id and row_id in self.tree.selection():
            self.on_select(row_id)

    def _handle_select(self, _event: tk.Event) -> None:
        if self._updating_tree or self._suppress_selection_callback:
            return
        region_id = self.selected_region_id()
        self.on_select(region_id)

    def _clear_selection_suppression(self) -> None:
        self._suppress_selection_callback = False

    def _toggle_checked(self, region_id: str) -> None:
        if region_id in self._checked_region_ids:
            self._checked_region_ids.remove(region_id)
            checked = False
        else:
            self._checked_region_ids.add(region_id)
            checked = True
        if region_id in self.tree.get_children():
            self.tree.set(region_id, "checked", self._check_mark(region_id))
        self.on_check_changed(region_id, checked)

    def _check_mark(self, region_id: str) -> str:
        return CHECKED_MARK if region_id in self._checked_region_ids else UNCHECKED_MARK

    def _rename(self) -> None:
        self.on_rename(self.name_var.get().strip())

    @staticmethod
    def _int_value(
        variable: tk.IntVar,
        fallback: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            value = int(variable.get())
        except (tk.TclError, ValueError):
            value = fallback
        return max(minimum, min(maximum, value))

