from __future__ import annotations

from typing import Callable

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

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
MAX_ZOOM = 16.0


class CanvasView(QWidget):
    def __init__(
        self,
        on_region_drawn: Callable[[str, dict, list[Point]], bool],
        on_region_selected: Callable[[str | None], None],
        on_region_moved: Callable[[str, float, float], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_region_drawn = on_region_drawn
        self.on_region_selected = on_region_selected
        self.on_region_moved = on_region_moved

        self.image_item: ImageItem | None = None
        self.tool = TOOL_RECT
        self.selected_region_id: str | None = None
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._qimage: QImage | None = None
        self._drawing_start: Point | None = None
        self._current_point: Point | None = None
        self._freehand_points: list[Point] = []
        self._moving_region_id: str | None = None
        self._move_last_point: Point | None = None
        self._panning = False
        self._last_pan: QPointF | None = None
        self._space_down = False
        self._fit_when_ready = False

        self.setMinimumSize(420, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self._update_cursor()

    def set_image_item(self, image_item: ImageItem | None) -> None:
        self.image_item = image_item
        self.selected_region_id = None
        self._qimage = _pil_to_qimage(image_item.image) if image_item is not None else None
        self._reset_drawing()
        if image_item is not None:
            self._fit_when_ready = True
            if self._current_canvas_size_is_effective():
                self.fit_to_window()
            else:
                self.update()
        else:
            self._fit_when_ready = False
            self.update()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._reset_drawing()
        self._update_cursor()
        self.update()

    def set_selected_region(self, region_id: str | None) -> None:
        if self.selected_region_id == region_id:
            return
        self.selected_region_id = region_id
        self.update()

    def fit_to_window(self) -> None:
        if self.image_item is None:
            return
        canvas_width = max(1, self.width())
        canvas_height = max(1, self.height())
        if not self._canvas_size_is_effective(canvas_width, canvas_height):
            self._fit_when_ready = True
            return
        image = self.image_item.image
        self.zoom = min(canvas_width / image.width, canvas_height / image.height) * 0.92
        self.zoom = self._clamp_zoom(self.zoom)
        self.offset_x = (canvas_width - image.width * self.zoom) / 2
        self.offset_y = (canvas_height - image.height * self.zoom) / 2
        self._fit_when_ready = False
        self.update()

    def redraw(self) -> None:
        self.update()

    def image_to_canvas(self, point: Point) -> QPointF:
        return QPointF(
            self.offset_x + point[0] * self.zoom,
            self.offset_y + point[1] * self.zoom,
        )

    def canvas_to_image(self, x: float, y: float) -> Point:
        return (
            (x - self.offset_x) / self.zoom,
            (y - self.offset_y) / self.zoom,
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f2f4f7"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.image_item is None or self._qimage is None:
            painter.setPen(QColor("#67707a"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "导入图片后开始绘制闭合区域",
            )
            return

        image = self.image_item.image
        target = QRectF(
            self.offset_x,
            self.offset_y,
            image.width * self.zoom,
            image.height * self.zoom,
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, self._qimage)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self._draw_regions(painter)
        self._draw_preview(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override.
        self.setFocus()
        if self.image_item is None:
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._start_pan(event.position())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._space_down or self.tool == TOOL_HAND:
            self._start_pan(event.position())
            return

        point = self.canvas_to_image(event.position().x(), event.position().y())
        if self.tool == TOOL_SELECT:
            region_id = self._region_at(point)
            self.selected_region_id = region_id
            self.on_region_selected(region_id)
            if region_id is not None:
                self._start_region_move(region_id, point)
            self.update()
            return

        self._drawing_start = point
        self._current_point = point
        self._freehand_points = [point] if self.tool == TOOL_FREEHAND else []
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override.
        if self._panning:
            self._pan_to(event.position())
            return
        if self._moving_region_id is not None:
            self._move_region_to(event.position())
            return
        if self.image_item is None or self._drawing_start is None:
            return
        point = self.canvas_to_image(event.position().x(), event.position().y())
        self._current_point = point
        if self.tool == TOOL_FREEHAND:
            if not self._freehand_points or distance(self._freehand_points[-1], point) >= 3.0:
                self._freehand_points.append(point)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override.
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._end_pan()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._moving_region_id is not None:
            self._end_region_move()
            return
        if self._panning:
            self._end_pan()
            return
        if self.image_item is None or self._drawing_start is None:
            return
        self._current_point = self.canvas_to_image(event.position().x(), event.position().y())
        self._commit_shape()
        self._reset_drawing()
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override.
        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        position = event.position()
        self._zoom_at(position.x(), position.y(), factor)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override.
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self._update_cursor()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override.
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            self._end_pan()
            self._update_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override.
        super().resizeEvent(event)
        if self.image_item is None:
            self.update()
            return
        if not self._current_canvas_size_is_effective():
            self._fit_when_ready = True
            return
        if self._fit_when_ready:
            self.fit_to_window()
        else:
            self.update()

    def _draw_regions(self, painter: QPainter) -> None:
        if self.image_item is None:
            return
        for region in self.image_item.regions:
            if not region.visible:
                continue
            polygon = QPolygonF([self.image_to_canvas(point) for point in region.polygon_points])
            selected = region.id == self.selected_region_id
            fill_color = QColor(28, 126, 214, 72) if region.is_valid else QColor(217, 72, 15, 72)
            outline_color = QColor("#f08c00") if selected else QColor("#1c7ed6")
            if not region.is_valid and not selected:
                outline_color = QColor("#d9480f")
            painter.setBrush(fill_color)
            painter.setPen(QPen(outline_color, 3 if selected else 2))
            painter.drawPolygon(polygon)

    def _draw_preview(self, painter: QPainter) -> None:
        if self._drawing_start is None:
            return
        pen = QPen(QColor("#212529"), 2)
        pen.setDashPattern([5, 3])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.tool in {TOOL_RECT, TOOL_ELLIPSE} and self._current_point is not None:
            start = self.image_to_canvas(self._drawing_start)
            current = self.image_to_canvas(self._current_point)
            rect = QRectF(start, current).normalized()
            if self.tool == TOOL_RECT:
                painter.drawRect(rect)
            else:
                painter.drawEllipse(rect)
        elif self.tool == TOOL_FREEHAND and len(self._freehand_points) >= 2:
            painter.drawPolyline(QPolygonF([self.image_to_canvas(point) for point in self._freehand_points]))

    def _zoom_at(self, canvas_x: float, canvas_y: float, factor: float) -> None:
        if self.image_item is None:
            return
        image_point = self.canvas_to_image(canvas_x, canvas_y)
        self.zoom = self._clamp_zoom(self.zoom * factor)
        self.offset_x = canvas_x - image_point[0] * self.zoom
        self.offset_y = canvas_y - image_point[1] * self.zoom
        self.update()

    def _start_pan(self, point: QPointF) -> None:
        self._panning = True
        self._last_pan = QPointF(point)
        self._update_cursor()

    def _pan_to(self, point: QPointF) -> None:
        if not self._panning or self._last_pan is None:
            return
        self.offset_x += point.x() - self._last_pan.x()
        self.offset_y += point.y() - self._last_pan.y()
        self._last_pan = QPointF(point)
        self.update()

    def _end_pan(self) -> None:
        self._panning = False
        self._last_pan = None
        self._update_cursor()

    def _start_region_move(self, region_id: str, point: Point) -> None:
        self._moving_region_id = region_id
        self._move_last_point = point
        self._update_cursor()

    def _move_region_to(self, position: QPointF) -> None:
        if self._moving_region_id is None or self._move_last_point is None:
            return
        current_point = self.canvas_to_image(position.x(), position.y())
        dx = current_point[0] - self._move_last_point[0]
        dy = current_point[1] - self._move_last_point[1]
        if dx == 0 and dy == 0:
            return
        if self.on_region_moved(self._moving_region_id, dx, dy):
            self._move_last_point = current_point
            self.update()

    def _end_region_move(self) -> None:
        self._moving_region_id = None
        self._move_last_point = None
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._panning or self._moving_region_id is not None or self._space_down or self.tool == TOOL_HAND:
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        elif self.tool == TOOL_SELECT:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

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

    def _region_at(self, point: Point) -> str | None:
        if self.image_item is None:
            return None
        for region in reversed(self.image_item.regions):
            if region.visible and point_in_polygon(point, region.polygon_points, include_boundary=True):
                return region.id
        return None

    def _reset_drawing(self) -> None:
        self._drawing_start = None
        self._current_point = None
        self._freehand_points = []
        self._moving_region_id = None
        self._move_last_point = None
        self._panning = False
        self._last_pan = None

    def _clamp_zoom(self, value: float) -> float:
        return max(MIN_ZOOM, min(float(value), MAX_ZOOM))

    def _current_canvas_size_is_effective(self) -> bool:
        return self._canvas_size_is_effective(self.width(), self.height())

    @staticmethod
    def _canvas_size_is_effective(width: int, height: int) -> bool:
        return width >= MIN_EFFECTIVE_CANVAS_SIZE and height >= MIN_EFFECTIVE_CANVAS_SIZE


def _pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy()
