from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .region import Region


@dataclass
class ImageItem:
    path: Path
    image: Image.Image
    regions: list[Region] = field(default_factory=list)
    exported: bool = False

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def file_name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def valid_region_count(self) -> int:
        return sum(1 for region in self.regions if region.is_valid)

    @property
    def has_invalid_regions(self) -> bool:
        return any(not region.is_valid for region in self.regions)

