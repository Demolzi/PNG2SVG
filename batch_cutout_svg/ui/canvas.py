from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageTk

from batch_cutout_svg.core.geometry import (
    Point,
    distance,
    ellipse_to_points,
    point_in_polygon,
    rect_to_points,
    simplify_points,
)
from batch_cutout_svg.models import ImageItem

TOOL_SELECT = "select"
TOOL_HAND = "hand"
TOOL_RECT = "rect"
TOOL_ELLIPSE = "ellipse"
TOOL_FREEHAND = "freehand"
MIN_EFFECTIVE_CANVAS_SIZE = 20
MIN_ZOOM = 0.01
MAX_PREVIEW_SIDE = 2400


class CanvasView(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        on_region_drawn: Callable[[str, dict, list[Point]], bool],
        on_region_selected: Callable[[str | None], None],
        on_region_moved: Callable[[str, float, float], bool],
    ) -> None:
        super().__init__(master)
        self.on_region_drawn = on_region_drawn
        self.on_region_selected = on_region_selected
        self.on_region_moved = on_region_moved

        self.canvas = tk.Canvas(self, background="#f2f4f7", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.image_item: ImageItem | None = None
        self.tool = TOOL_RECT
        self.selected_region_id: str | None = None
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._tk_image: ImageTk.PhotoImage | None = None
        self._preview_cache_key: tuple[int, int, int] | None = None
        self._preview_cache_image: Image.Image | None = None
        self._drawing_start: Point | None = None
        self._current_point: Point | None = None
        self._freehand_points: list[Point] = []
        self._moving_region_id: str | None = None
        self._move_last_point: Point | None = None
        self._panning = False
        self._last_pan: tuple[int, int] | None = None
        self._space_down = False
        self._fit_when_ready = False
        self._last_canvas_size: tuple[int, int] = (0, 0)

        self.canvas.bind("<Configure>", self._handle_configure)
        self.canvas.bind("<Enter>", lambda _event: self.canvas.focus_set())
        self.canvas.bind("<ButtonPress-1>", self._left_down)
        self.canvas.bind("<B1-Motion>", self._left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._left_up)
        self.canvas.bind("<ButtonPress-2>", self._middle_down)
        self.canvas.bind("<B2-Motion>", self._middle_drag)
        self.canvas.bind("<ButtonRelease-2>", self._middle_up)
        self.canvas.bind("<MouseWheel>", self._mouse_wheel)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_at(event.x, event.y, 1.1))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_at(event.x, event.y, 0.9))
        self.canvas.bind("<KeyPress-space>", self._space_press)
        self.canvas.bind("<KeyRelease-space>", self._space_release)
        self._update_cursor()

    def set_image_item(self, image_item: ImageItem | None) -> None:
        self.image_item = image_item
        self.selected_region_id = None
        self._preview_cache_key = None
        self._preview_cache_image = None
        self._reset_drawing()
        if image_item is not None:
            self._fit_when_ready = True
            if self._current_canvas_size_is_effective():
                self.fit_to_window()
            else:
                self.redraw()
        else:
            self._fit_when_ready = False
            self.redraw()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._reset_drawing()
        self._update_cursor()
        self.redraw()

    def set_selected_region(self, region_id: str | None) -> None:
        if self.selected_region_id == region_id:
            return
        self.selected_region_id = region_id
        self.redraw()

    def fit_to_window(self) -> None:
        if self.image_item is None:
            return
        canvas_width, canvas_height = self._canvas_size()
        if not self._canvas_size_is_effective(canvas_width, canvas_height):
            self._fit_when_ready = True
            return
        image = self.image_item.image
        self.zoom = min(canvas_width / image.width, canvas_height / image.height) * 0.92
        self.zoom = self._clamp_zoom(self.zoom)
        self.offset_x = (canvas_width - image.width * self.zoom) / 2
        self.offset_y = (canvas_height - image.height * self.zoom) / 2
        self._fit_when_ready = False
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.image_item is None:
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="导入图片后开始绘制闭合区域",
                fill="#67707a",
            )
            return

        image = self.image_item.image
        self.zoom = self._clamp_zoom(self.zoom)
        scaled_width = max(1, int(image.width * self.zoom))
        scaled_height = max(1, int(image.height * self.zoom))
        max_side = max(scaled_width, scaled_height)
        if max_side > MAX_PREVIEW_SIDE:
            factor = MAX_PREVIEW_SIDE / max_side
            self.zoom = self._clamp_zoom(self.zoom * factor)
            scaled_width = max(1, int(image.width * self.zoom))
            scaled_height = max(1, int(image.height * self.zoom))

        cache_key = (id(image), scaled_width, scaled_height)
        if self._preview_cache_key == cache_key and self._preview_cache_image is not None:
            scaled = self._preview_cache_image
        else:
            resampling = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
            scaled = image.resize((scaled_width, scaled_height), resampling)
            self._preview_cache_key = cache_key
            self._preview_cache_image = scaled
        self._tk_image = ImageTk.PhotoImage(scaled)
        self.canvas.create_image(
            self.offset_x,
            self.offset_y,
            anchor="nw",
            image=self._tk_image,
            tags=("image",),
        )
        self._draw_regions()
        self._draw_preview()

    def image_to_canvas(self, point: Point) -> tuple[float, float]:
        return (
            self.offset_x + point[0] * self.zoom,
            self.offset_y + point[1] * self.zoom,
        )

    def canvas_to_image(self, x: float, y: float) -> Point:
        return (
            (x - self.offset_x) / self.zoom,
            (y - self.offset_y) / self.zoom,
        )

    def _draw_regions(self) -> None:
        if self.image_item is None:
            return
        for region in self.image_item.regions:
            if not region.visible:
                continue
            coords: list[float] = []
            for point in region.polygon_points:
                canvas_point = self.image_to_canvas(point)
                coords.extend(canvas_point)
            selected = region.id == self.selected_region_id
            fill = "#1c7ed6" if region.is_valid else "#d9480f"
            outline = "#f08c00" if selected else fill
            self.canvas.create_polygon(
                coords,
                fill=fill,
                stipple="gray25",
                outline=outline,
                width=3 if selected else 2,
                tags=("region", region.id),
            )

    def _draw_preview(self) -> None:
        if self._drawing_start is None:
            return
        if self.tool in {TOOL_RECT, TOOL_ELLIPSE} and self._current_point is not None:
            x1, y1 = self.image_to_canvas(self._drawing_start)
            x2, y2 = self.image_to_canvas(self._current_point)
            if self.tool == TOOL_RECT:
                self.canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    outline="#212529",
                    width=2,
                    dash=(5, 3),
                    tags=("preview",),
                )
            else:
                self.canvas.create_oval(
                    x1,
                    y1,
                    x2,
                    y2,
                    outline="#212529",
                    width=2,
                    dash=(5, 3),
                    tags=("preview",),
                )
        elif self.tool == TOOL_FREEHAND and len(self._freehand_points) >= 2:
            coords: list[float] = []
            for point in self._freehand_points:
                coords.extend(self.image_to_canvas(point))
            self.canvas.create_line(
                coords,
                fill="#212529",
                width=2,
                smooth=True,
                tags=("preview",),
            )

    def _left_down(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        if self.image_item is None:
            return
        if self._space_down or self.tool == TOOL_HAND:
            self._start_pan(event)
            return
        point = self.canvas_to_image(event.x, event.y)
        if self.tool == TOOL_SELECT:
            region_id = self._region_at(point)
            self.selected_region_id = region_id
            self.on_region_selected(region_id)
            if region_id is not None:
                self._start_region_move(region_id, point)
            self.redraw()
            return
        self._drawing_start = point
        self._current_point = point
        self._freehand_points = [point] if self.tool == TOOL_FREEHAND else []
        self.redraw()

    def _left_drag(self, event: tk.Event) -> None:
        if self._panning:
            self._pan_to(event)
            return
        if self._moving_region_id is not None:
            self._move_region_to(event)
            return
        if self.image_item is None or self._drawing_start is None:
            return
        point = self.canvas_to_image(event.x, event.y)
        self._current_point = point
        if self.tool == TOOL_FREEHAND:
            if not self._freehand_points or distance(self._freehand_points[-1], point) >= 3.0:
                self._freehand_points.append(point)
        self.redraw()

    def _left_up(self, event: tk.Event) -> None:
        if self._moving_region_id is not None:
            self._end_region_move()
            return
        if self._panning:
            self._end_pan()
            return
        if self.image_item is None or self._drawing_start is None:
            return
        self._current_point = self.canvas_to_image(event.x, event.y)
        self._commit_shape()
        self._reset_drawing()
        self.redraw()

    def _middle_down(self, event: tk.Event) -> None:
        self._start_pan(event)

    def _middle_drag(self, event: tk.Event) -> None:
        self._pan_to(event)

    def _middle_up(self, _event: tk.Event) -> None:
        self._end_pan()

    def _mouse_wheel(self, event: tk.Event) -> None:
        factor = 1.1 if event.delta > 0 else 0.9
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, canvas_x: float, canvas_y: float, factor: float) -> None:
        if self.image_item is None:
            return
        image_point = self.canvas_to_image(canvas_x, canvas_y)
        self.zoom = self._clamp_zoom(self.zoom * factor)
        self.offset_x = canvas_x - image_point[0] * self.zoom
        self.offset_y = canvas_y - image_point[1] * self.zoom
        self.redraw()

    def _space_press(self, _event: tk.Event) -> None:
        self._space_down = True
        self._update_cursor()

    def _space_release(self, _event: tk.Event) -> None:
        self._space_down = False
        self._end_pan()
        self._update_cursor()

    def _start_pan(self, event: tk.Event) -> None:
        self._panning = True
        self._last_pan = (event.x, event.y)
        self._update_cursor()

    def _pan_to(self, event: tk.Event) -> None:
        if not self._panning or self._last_pan is None:
            return
        last_x, last_y = self._last_pan
        self.offset_x += event.x - last_x
        self.offset_y += event.y - last_y
        self._last_pan = (event.x, event.y)
        self.redraw()

    def _end_pan(self) -> None:
        self._panning = False
        self._last_pan = None
        self._update_cursor()

    def _start_region_move(self, region_id: str, point: Point) -> None:
        self._moving_region_id = region_id
        self._move_last_point = point
        self._update_cursor()

    def _move_region_to(self, event: tk.Event) -> None:
        if self._moving_region_id is None or self._move_last_point is None:
            return
        current_point = self.canvas_to_image(event.x, event.y)
        dx = current_point[0] - self._move_last_point[0]
        dy = current_point[1] - self._move_last_point[1]
        if dx == 0 and dy == 0:
            return
        if self.on_region_moved(self._moving_region_id, dx, dy):
            self._move_last_point = current_point
            self.redraw()

    def _end_region_move(self) -> None:
        self._moving_region_id = None
        self._move_last_point = None
        self._update_cursor()

    def _handle_configure(self, event: tk.Event) -> None:
        new_size = (int(event.width), int(event.height))
        if new_size == self._last_canvas_size:
            return
        self._last_canvas_size = new_size
        if self.image_item is None:
            self.redraw()
            return
        if not self._canvas_size_is_effective(*new_size):
            self._fit_when_ready = True
            return
        if self._fit_when_ready:
            self.fit_to_window()
        else:
            self.redraw()

    def _canvas_size(self) -> tuple[int, int]:
        return int(self.canvas.winfo_width()), int(self.canvas.winfo_height())

    def _current_canvas_size_is_effective(self) -> bool:
        return self._canvas_size_is_effective(*self._canvas_size())

    @staticmethod
    def _canvas_size_is_effective(width: int, height: int) -> bool:
        return width >= MIN_EFFECTIVE_CANVAS_SIZE and height >= MIN_EFFECTIVE_CANVAS_SIZE

    def _clamp_zoom(self, value: float) -> float:
        max_zoom = 16.0
        if self.image_item is not None:
            image = self.image_item.image
            max_zoom = min(max_zoom, MAX_PREVIEW_SIDE / max(image.width, image.height))
        min_zoom = min(MIN_ZOOM, max_zoom)
        return max(min_zoom, min(value, max_zoom))

    def _update_cursor(self) -> None:
        if self._panning or self._moving_region_id is not None or self._space_down or self.tool == TOOL_HAND:
            cursor = "fleur"
        elif self.tool == TOOL_SELECT:
            cursor = "arrow"
        else:
            cursor = "crosshair"
        self.canvas.configure(cursor=cursor)

    def _commit_shape(self) -> None:
        if self._drawing_start is None or self._current_point is None:
            return
        start = self._drawing_start
        end = self._current_point
        if self.tool == TOOL_RECT:
            x = min(start[0], end[0])
            y = min(start[1], end[1])
            width = abs(end[0] - start[0])
            height = abs(end[1] - start[1])
            data = {"type": "rect", "x": x, "y": y, "width": width, "height": height}
            points = rect_to_points(x, y, width, height)
            self.on_region_drawn(TOOL_RECT, data, points)
        elif self.tool == TOOL_ELLIPSE:
            cx = (start[0] + end[0]) / 2
            cy = (start[1] + end[1]) / 2
            rx = abs(end[0] - start[0]) / 2
            ry = abs(end[1] - start[1]) / 2
            data = {"type": "ellipse", "cx": cx, "cy": cy, "rx": rx, "ry": ry}
            points = ellipse_to_points(cx, cy, rx, ry, segments=128)
            self.on_region_drawn(TOOL_ELLIPSE, data, points)
        elif self.tool == TOOL_FREEHAND:
            points = simplify_points(self._freehand_points, tolerance=1.5)
            data = {"type": "freehand", "points": points}
            self.on_region_drawn(TOOL_FREEHAND, data, points)

    def _select_region_at(self, point: Point) -> None:
        region_id = self._region_at(point)
        self.selected_region_id = region_id
        self.on_region_selected(region_id)
        self.redraw()

    def _region_at(self, point: Point) -> str | None:
        if self.image_item is None:
            return None
        for region in reversed(self.image_item.regions):
            if region.visible and point_in_polygon(point, region.polygon_points, include_boundary=True):
                return region.id
        return None

    def _point_inside_region(self, region_id: str, point: Point) -> bool:
        if self.image_item is None:
            return False
        region = next((item for item in self.image_item.regions if item.id == region_id), None)
        return bool(
            region is not None
            and region.visible
            and point_in_polygon(point, region.polygon_points, include_boundary=True)
        )

    def _reset_drawing(self) -> None:
        self._drawing_start = None
        self._current_point = None
        self._freehand_points = []
        self._moving_region_id = None
        self._move_last_point = None
        self._panning = False
        self._last_pan = None

