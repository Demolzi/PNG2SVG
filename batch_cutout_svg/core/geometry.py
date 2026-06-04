from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point as ShapelyPoint, Polygon
from shapely.validation import explain_validity

Point = tuple[float, float]
EPSILON = 1e-7


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    error_message: str | None = None


def normalize_points(points: list[Point]) -> list[Point]:
    normalized: list[Point] = []
    for x, y in points:
        point = (float(x), float(y))
        if not normalized or distance(normalized[-1], point) > EPSILON:
            normalized.append(point)
    if len(normalized) > 1 and distance(normalized[0], normalized[-1]) <= EPSILON:
        normalized.pop()
    return normalized


def rect_to_points(x: float, y: float, width: float, height: float) -> list[Point]:
    left, right = sorted((x, x + width))
    top, bottom = sorted((y, y + height))
    return [(left, top), (right, top), (right, bottom), (left, bottom)]


def ellipse_to_points(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    segments: int = 128,
) -> list[Point]:
    segments = max(12, int(segments))
    rx = abs(rx)
    ry = abs(ry)
    return [
        (
            cx + math.cos((math.tau * i) / segments) * rx,
            cy + math.sin((math.tau * i) / segments) * ry,
        )
        for i in range(segments)
    ]


def polygon_area(points: list[Point]) -> float:
    polygon = _polygon_or_none(points)
    return 0.0 if polygon is None else float(abs(polygon.area))


def bounding_box(points: list[Point]) -> tuple[float, float, float, float]:
    points = normalize_points(points)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def simplify_points(points: list[Point], tolerance: float = 1.5) -> list[Point]:
    points = normalize_points(points)
    if len(points) <= 3:
        return points

    ring = LineString(points + [points[0]])
    simplified = ring.simplify(float(tolerance), preserve_topology=False)
    simplified_points = [(float(x), float(y)) for x, y in simplified.coords]
    return normalize_points(simplified_points)


def validate_polygon(
    points: list[Point],
    image_width: int,
    image_height: int,
    existing_polygons: list[list[Point]] | None = None,
    min_area: float = 25.0,
) -> ValidationResult:
    points = normalize_points(points)
    if len(points) < 3:
        return ValidationResult(False, "当前区域点数不足，请重新绘制。")
    if not polygon_inside_image(points, image_width, image_height):
        return ValidationResult(False, "当前区域超出图片边界。")

    polygon = _polygon_or_none(points)
    if polygon is None:
        return ValidationResult(False, "当前区域无法形成有效闭合多边形。")
    if not polygon.is_valid:
        reason = explain_validity(polygon)
        return ValidationResult(False, f"当前曲线自交或无效，请重新绘制。{reason}")
    if polygon.area < min_area:
        return ValidationResult(False, "当前区域面积过小。")

    for old_points in existing_polygons or []:
        old_polygon = _polygon_or_none(old_points)
        if old_polygon is None or old_polygon.is_empty:
            continue
        if polygon.boundary.intersects(old_polygon.boundary):
            return ValidationResult(False, "当前区域与已有区域边界交叉或重合。")
        if polygon.contains(old_polygon):
            return ValidationResult(False, "当前区域包含已有区域，当前版本暂不支持包含关系。")
        if old_polygon.contains(polygon):
            return ValidationResult(False, "已有区域包含当前区域，当前版本暂不支持包含关系。")
        if polygon.intersection(old_polygon).area > EPSILON:
            return ValidationResult(False, "当前区域与已有区域重叠。")

    return ValidationResult(True)


def polygon_inside_image(points: list[Point], image_width: int, image_height: int) -> bool:
    return all(0 <= x <= image_width and 0 <= y <= image_height for x, y in points)


def has_self_intersection(points: list[Point]) -> bool:
    points = normalize_points(points)
    if len(points) < 4:
        return False
    polygon = _polygon_or_none(points)
    return polygon is not None and not polygon.is_valid


def boundaries_intersect(first: list[Point], second: list[Point]) -> bool:
    first_polygon = _polygon_or_none(first)
    second_polygon = _polygon_or_none(second)
    if first_polygon is None or second_polygon is None:
        return False
    return bool(first_polygon.boundary.intersects(second_polygon.boundary))


def polygons_overlap(first: list[Point], second: list[Point]) -> bool:
    first_polygon = _polygon_or_none(first)
    second_polygon = _polygon_or_none(second)
    if first_polygon is None or second_polygon is None:
        return False
    return first_polygon.intersection(second_polygon).area > EPSILON


def polygon_contains_polygon(outer: list[Point], inner: list[Point]) -> bool:
    outer_polygon = _polygon_or_none(outer)
    inner_polygon = _polygon_or_none(inner)
    if outer_polygon is None or inner_polygon is None:
        return False
    return bool(outer_polygon.contains(inner_polygon))


def point_in_polygon(
    point: Point,
    polygon: list[Point],
    include_boundary: bool = False,
) -> bool:
    shape = _polygon_or_none(polygon)
    if shape is None:
        return False
    shapely_point = ShapelyPoint(float(point[0]), float(point[1]))
    if include_boundary:
        return bool(shape.covers(shapely_point))
    return bool(shape.contains(shapely_point))


def segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    return bool(LineString([a1, a2]).intersects(LineString([b1, b2])))


def orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def point_on_segment(point: Point, start: Point, end: Point) -> bool:
    return bool(LineString([start, end]).distance(ShapelyPoint(point)) <= EPSILON)


def _polygon_or_none(points: list[Point]) -> Polygon | None:
    points = normalize_points(points)
    if len(points) < 3:
        return None
    try:
        return Polygon(points)
    except (TypeError, ValueError):
        return None
