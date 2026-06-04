from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

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
    export_count: int = 0

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.id

    @property
    def shape_label(self) -> str:
        return SHAPE_LABELS.get(self.shape_type, self.shape_type)

    @property
    def status_label(self) -> str:
        return "合法" if self.is_valid else f"非法: {self.error_message or '未知原因'}"


REGION_ID_PATTERN = re.compile(r"^region(\d+)$")


def next_region_id(existing_count: int) -> str:
    return f"region{existing_count + 1:03d}"


def next_available_region_id(existing_ids: Iterable[str]) -> str:
    used_numbers: set[int] = set()
    for region_id in existing_ids:
        match = REGION_ID_PATTERN.match(region_id)
        if match is not None:
            used_numbers.add(int(match.group(1)))

    candidate = 1
    while candidate in used_numbers:
        candidate += 1
    return f"region{candidate:03d}"
