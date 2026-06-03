from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Point = tuple[float, float]

SHAPE_LABELS = {
    "rect": "矩形",
    "ellipse": "椭圆",
    "freehand": "自由曲线",
}


@dataclass
class Region:
    id: str
    name: str
    shape_type: str
    data: dict[str, Any]
    polygon_points: list[Point]
    is_valid: bool = True
    error_message: str | None = None
    visible: bool = True

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.id

    @property
    def shape_label(self) -> str:
        return SHAPE_LABELS.get(self.shape_type, self.shape_type)

    @property
    def status_label(self) -> str:
        return "合法" if self.is_valid else f"非法: {self.error_message or '未知原因'}"


def next_region_id(existing_count: int) -> str:
    return f"region{existing_count + 1:03d}"

