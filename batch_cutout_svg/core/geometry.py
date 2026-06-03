from __future__ import annotations

import math
from dataclasses import dataclass

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
    points = normalize_points(points)
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, current in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += current[0] * nxt[1] - nxt[0] * current[1]
    return abs(total) / 2.0


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

    def point_line_distance(point: Point, start: Point, end: Point) -> float:
        if distance(start, end) <= EPSILON:
            return distance(point, start)
        numerator = abs(
            (end[0] - start[0]) * (start[1] - point[1])
            - (start[0] - point[0]) * (end[1] - start[1])
        )
        return numerator / distance(start, end)

    def rdp(items: list[Point]) -> list[Point]:
        if len(items) <= 2:
            return items
        start, end = items[0], items[-1]
        max_distance = -1.0
        max_index = 0
        for index in range(1, len(items) - 1):
            candidate = point_line_distance(items[index], start, end)
            if candidate > max_distance:
                max_distance = candidate
                max_index = index
        if max_distance > tolerance:
            left = rdp(items[: max_index + 1])
            right = rdp(items[max_index:])
            return left[:-1] + right
        return [start, end]

    simplified = rdp(points + [points[0]])
    if simplified and distance(simplified[0], simplified[-1]) <= EPSILON:
        simplified.pop()
    return normalize_points(simplified)


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
    if has_self_intersection(points):
        return ValidationResult(False, "当前曲线自交，请重新绘制。")
    if polygon_area(points) < min_area:
        return ValidationResult(False, "当前区域面积过小。")

    for old in existing_polygons or []:
        old = normalize_points(old)
        if not old:
            continue
        if boundaries_intersect(points, old):
            return ValidationResult(False, "当前区域与已有区域边界交叉或重合。")
        if polygon_contains_polygon(points, old):
            return ValidationResult(False, "当前区域包含已有区域，第一版暂不支持包含关系。")
        if polygon_contains_polygon(old, points):
            return ValidationResult(False, "已有区域包含当前区域，第一版暂不支持包含关系。")
        if polygons_overlap(points, old):
            return ValidationResult(False, "当前区域与已有区域重叠。")

    return ValidationResult(True)


def polygon_inside_image(points: list[Point], image_width: int, image_height: int) -> bool:
    return all(0 <= x <= image_width and 0 <= y <= image_height for x, y in points)


def has_self_intersection(points: list[Point]) -> bool:
    points = normalize_points(points)
    count = len(points)
    if count < 4:
        return False
    for i in range(count):
        a1, a2 = points[i], points[(i + 1) % count]
        for j in range(i + 1, count):
            if abs(i - j) == 1:
                continue
            if i == 0 and j == count - 1:
                continue
            b1, b2 = points[j], points[(j + 1) % count]
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def boundaries_intersect(first: list[Point], second: list[Point]) -> bool:
    first = normalize_points(first)
    second = normalize_points(second)
    for i in range(len(first)):
        a1, a2 = first[i], first[(i + 1) % len(first)]
        for j in range(len(second)):
            b1, b2 = second[j], second[(j + 1) % len(second)]
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def polygons_overlap(first: list[Point], second: list[Point]) -> bool:
    return any(point_in_polygon(point, second) for point in first) or any(
        point_in_polygon(point, first) for point in second
    )


def polygon_contains_polygon(outer: list[Point], inner: list[Point]) -> bool:
    return all(point_in_polygon(point, outer, include_boundary=False) for point in inner)


def point_in_polygon(
    point: Point,
    polygon: list[Point],
    include_boundary: bool = False,
) -> bool:
    polygon = normalize_points(polygon)
    if len(polygon) < 3:
        return False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if point_on_segment(point, start, end):
            return include_boundary

    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        xi, yi = current
        xj, yj = previous
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_intersection = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_intersection:
                inside = not inside
        previous = current
    return inside


def segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    d1 = orientation(a1, a2, b1)
    d2 = orientation(a1, a2, b2)
    d3 = orientation(b1, b2, a1)
    d4 = orientation(b1, b2, a2)

    if d1 * d2 < -EPSILON and d3 * d4 < -EPSILON:
        return True
    if abs(d1) <= EPSILON and point_on_segment(b1, a1, a2):
        return True
    if abs(d2) <= EPSILON and point_on_segment(b2, a1, a2):
        return True
    if abs(d3) <= EPSILON and point_on_segment(a1, b1, b2):
        return True
    if abs(d4) <= EPSILON and point_on_segment(a2, b1, b2):
        return True
    return False


def orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def point_on_segment(point: Point, start: Point, end: Point) -> bool:
    if abs(orientation(start, end, point)) > EPSILON:
        return False
    return (
        min(start[0], end[0]) - EPSILON
        <= point[0]
        <= max(start[0], end[0]) + EPSILON
        and min(start[1], end[1]) - EPSILON
        <= point[1]
        <= max(start[1], end[1]) + EPSILON
    )
