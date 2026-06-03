from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from batch_cutout_svg.models import ImageItem


class ImageListPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        on_select: Callable[[Path], None],
    ) -> None:
        super().__init__(master)
        self.on_select = on_select

        ttk.Label(self, text="图片列表").pack(anchor="w", padx=8, pady=(8, 4))
        columns = ("regions", "exported")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=18,
        )
        self.tree.heading("#0", text="文件")
        self.tree.heading("regions", text="区域")
        self.tree.heading("exported", text="导出")
        self.tree.column("#0", width=170, stretch=True)
        self.tree.column("regions", width=48, anchor="center", stretch=False)
        self.tree.column("exported", width=48, anchor="center", stretch=False)

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=(0, 8))

        self.tree.bind("<<TreeviewSelect>>", self._handle_select)

    def set_images(self, items: list[ImageItem]) -> None:
        current_selection = self.selected_path()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for item in items:
            iid = str(item.path)
            marker = "是" if item.exported else "否"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                text=item.file_name,
                values=(str(len(item.regions)), marker),
            )
        if current_selection and str(current_selection) in self.tree.get_children():
            self.tree.selection_set(str(current_selection))

    def select_path(self, path: Path) -> None:
        iid = str(path)
        if iid in self.tree.get_children():
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)

    def selected_path(self) -> Path | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return Path(selection[0])

    def _handle_select(self, _event: tk.Event) -> None:
        selected = self.selected_path()
        if selected is not None:
            self.on_select(selected)

