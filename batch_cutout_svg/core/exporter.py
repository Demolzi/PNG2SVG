from __future__ import annotations

import base64
from dataclasses import dataclass, field
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Callable

from batch_cutout_svg.models import ImageItem, Region

from .mask import CutoutOptions, create_cutout_png
from .naming import build_region_export_path


@dataclass
class ExportFailure:
    image_name: str
    region_name: str
    reason: str


@dataclass
class ExportSummary:
    exported_paths: list[Path] = field(default_factory=list)
    failures: list[ExportFailure] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.exported_paths)

    @property
    def failure_count(self) -> int:
        return len(self.failures)


def export_region_as_svg(
    image_item: ImageItem,
    region: Region,
    output_path: str | Path,
    feather_radius: float = 1.5,
    cutout_options: CutoutOptions | None = None,
) -> Path:
    if not region.is_valid:
        raise ValueError(region.error_message or "区域非法，无法导出。")

    resolved_options = cutout_options or CutoutOptions(feather_radius=feather_radius)
    cutout = create_cutout_png(
        image_item.image,
        region.polygon_points,
        feather_radius=feather_radius,
        options=resolved_options,
    )
    buffer = BytesIO()
    cutout.save(buffer, format="PNG")
    encoded_png = base64.b64encode(buffer.getvalue()).decode("ascii")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    title = escape(region.display_name)
    width, height = cutout.size
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f"  <title>{title}</title>\n"
        "  <desc>Embedded transparent PNG cutout, not vectorized SVG paths.</desc>\n"
        f'  <image href="data:image/png;base64,{encoded_png}" width="{width}" height="{height}" />\n'
        "</svg>\n"
    )
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def export_all(
    image_items: list[ImageItem],
    output_root: str | Path,
    feather_radius: float = 1.5,
    cutout_options: CutoutOptions | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ExportSummary:
    summary = ExportSummary()
    total_regions = sum(len(item.regions) for item in image_items)
    processed = 0
    resolved_options = cutout_options or CutoutOptions(feather_radius=feather_radius)

    for image_item in image_items:
        exported_for_image = 0
        for index, region in enumerate(image_item.regions, start=1):
            processed += 1
            try:
                if not region.is_valid:
                    raise ValueError(region.error_message or "区域非法。")
                output_path = build_region_export_path(
                    output_root,
                    image_item,
                    region,
                    index,
                )
                exported = export_region_as_svg(
                    image_item,
                    region,
                    output_path,
                    feather_radius=feather_radius,
                    cutout_options=resolved_options,
                )
                summary.exported_paths.append(exported)
                exported_for_image += 1
            except Exception as exc:  # noqa: BLE001 - batch export keeps going.
                summary.failures.append(
                    ExportFailure(
                        image_name=image_item.file_name,
                        region_name=region.display_name,
                        reason=str(exc),
                    )
                )
            if progress_callback is not None:
                progress_callback(processed, total_regions)
        if exported_for_image:
            image_item.exported = True

    return summary
