from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from batch_cutout_svg.models import Region


class RegionPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        on_select: Callable[[str], None],
        on_rename: Callable[[str], None],
        on_toggle_visible: Callable[[], None],
        on_delete: Callable[[], None],
        on_browse_output: Callable[[], None],
        on_export: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.on_select = on_select
        self.on_rename = on_rename
        self.on_toggle_visible = on_toggle_visible
        self.on_delete = on_delete
        self.on_browse_output = on_browse_output
        self.on_export = on_export

        self.name_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.feather_var = tk.DoubleVar(value=1.5)

        ttk.Label(self, text="区域列表").pack(anchor="w", padx=8, pady=(8, 4))
        columns = ("name", "type", "visible", "status")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=12,
        )
        for column, label, width in (
            ("name", "名称", 110),
            ("type", "类型", 72),
            ("visible", "显示", 48),
            ("status", "状态", 76),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="center", stretch=column == "name")
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)

        form = ttk.Frame(self)
        form.pack(fill="x", padx=8, pady=8)
        ttk.Label(form, text="区域名称").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(form, textvariable=self.name_var)
        name_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        form.columnconfigure(0, weight=1)
        ttk.Button(form, text="重命名", command=self._rename).grid(row=1, column=2, padx=(6, 0), sticky="ew")
        ttk.Button(form, text="显示/隐藏", command=self.on_toggle_visible).grid(row=2, column=0, sticky="ew")
        ttk.Button(form, text="删除区域", command=self.on_delete).grid(row=2, column=1, columnspan=2, padx=(6, 0), sticky="ew")

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
        ttk.Button(settings, text="导出全部 SVG", command=self.on_export).grid(
            row=3,
            column=1,
            sticky="ew",
            padx=(4, 8),
            pady=(2, 8),
        )
        settings.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

    def set_regions(self, regions: list[Region], selected_region_id: str | None) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for index, region in enumerate(regions, start=1):
            self.tree.insert(
                "",
                "end",
                iid=region.id,
                values=(
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
            self.name_var.set("")

    def selected_region_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def set_output_dir(self, value: str) -> None:
        self.output_dir_var.set(value)

    def output_dir(self) -> str:
        return self.output_dir_var.get().strip()

    def feather_radius(self) -> float:
        try:
            return max(0.0, float(self.feather_var.get()))
        except (tk.TclError, ValueError):
            return 1.5

    def set_progress(self, current: int, total: int) -> None:
        self.progress.configure(maximum=max(1, total), value=current)

    def _handle_select(self, _event: tk.Event) -> None:
        region_id = self.selected_region_id()
        if region_id:
            self.on_select(region_id)

    def _rename(self) -> None:
        self.on_rename(self.name_var.get().strip())

