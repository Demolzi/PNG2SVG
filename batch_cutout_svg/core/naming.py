from __future__ import annotations

import re
from pathlib import Path

from batch_cutout_svg.models import ImageItem, Region

ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename_part(value: str, fallback: str) -> str:
    cleaned = ILLEGAL_FILENAME_CHARS.sub("_", value.strip())
    cleaned = cleaned.rstrip(". ")
    return cleaned or fallback


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    copy_index = 1
    while True:
        candidate = parent / f"{stem}_copy{copy_index}{suffix}"
        if not candidate.exists():
            return candidate
        copy_index += 1


def image_output_dir(output_root: str | Path, image_item: ImageItem) -> Path:
    image_stem = sanitize_filename_part(image_item.stem, "image")
    return Path(output_root) / image_stem


def build_region_export_path(
    output_root: str | Path,
    image_item: ImageItem,
    region: Region,
    index: int,
) -> Path:
    image_stem = sanitize_filename_part(image_item.stem, "image")
    region_name = sanitize_filename_part(region.display_name, region.id)
    file_name = f"{image_stem}_{index:03d}_{region_name}.svg"
    return unique_path(image_output_dir(output_root, image_item) / file_name)

