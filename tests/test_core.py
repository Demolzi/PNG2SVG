from __future__ import annotations

import base64
import shutil
import unittest
import uuid
from pathlib import Path

from PIL import Image

from batch_cutout_svg.core.exporter import export_region_as_svg
from batch_cutout_svg.core.geometry import (
    point_in_polygon,
    rect_to_points,
    validate_polygon,
)
from batch_cutout_svg.core.mask import create_cutout_png
from batch_cutout_svg.core.naming import sanitize_filename_part, unique_path
from batch_cutout_svg.models import ImageItem, Region


def make_test_dir() -> Path:
    path = Path(".tmp") / "tests" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


class GeometryTests(unittest.TestCase):
    def test_valid_rectangle(self) -> None:
        points = rect_to_points(10, 10, 40, 30)
        result = validate_polygon(points, 100, 100)
        self.assertTrue(result.is_valid)

    def test_self_intersection_is_rejected(self) -> None:
        points = [(10, 10), (60, 60), (10, 60), (60, 10)]
        result = validate_polygon(points, 100, 100)
        self.assertFalse(result.is_valid)
        self.assertIn("自交", result.error_message or "")

    def test_overlap_is_rejected(self) -> None:
        first = rect_to_points(10, 10, 40, 40)
        second = rect_to_points(30, 30, 40, 40)
        result = validate_polygon(second, 120, 120, existing_polygons=[first])
        self.assertFalse(result.is_valid)

    def test_contains_is_rejected(self) -> None:
        first = rect_to_points(20, 20, 20, 20)
        second = rect_to_points(10, 10, 60, 60)
        result = validate_polygon(second, 120, 120, existing_polygons=[first])
        self.assertFalse(result.is_valid)
        self.assertIn("包含", result.error_message or "")

    def test_point_in_polygon(self) -> None:
        polygon = rect_to_points(10, 10, 50, 50)
        self.assertTrue(point_in_polygon((20, 20), polygon))
        self.assertFalse(point_in_polygon((80, 80), polygon))


class NamingTests(unittest.TestCase):
    def test_sanitize_filename(self) -> None:
        self.assertEqual(sanitize_filename_part('a/b:c*?"<>|', "fallback"), "a_b_c______")
        self.assertEqual(sanitize_filename_part("   ", "fallback"), "fallback")

    def test_unique_path(self) -> None:
        tmp = make_test_dir()
        try:
            path = tmp / "item.svg"
            path.write_text("x", encoding="utf-8")
            self.assertEqual(unique_path(path).name, "item_copy1.svg")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class MaskAndExporterTests(unittest.TestCase):
    def test_mask_has_transparent_background(self) -> None:
        image = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
        polygon = rect_to_points(5, 5, 10, 10)
        cutout = create_cutout_png(image, polygon, feather_radius=0)
        self.assertEqual(cutout.size, (10, 10))
        self.assertEqual(cutout.getpixel((5, 5))[3], 255)

    def test_export_svg_embeds_png(self) -> None:
        tmp = make_test_dir()
        try:
            image = Image.new("RGBA", (20, 20), (0, 128, 255, 255))
            item = ImageItem(path=Path("sample.png"), image=image)
            region = Region(
                id="region001",
                name="part",
                shape_type="rect",
                data={},
                polygon_points=rect_to_points(2, 3, 8, 9),
            )
            output = export_region_as_svg(item, region, tmp / "out.svg", feather_radius=0)
            text = output.read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("data:image/png;base64,", text)
            encoded = text.split("data:image/png;base64,", 1)[1].split('"', 1)[0]
            self.assertGreater(len(base64.b64decode(encoded)), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
