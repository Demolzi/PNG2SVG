from __future__ import annotations

import base64
import shutil
import unittest
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from batch_cutout_svg.core.exporter import export_region_as_svg
from batch_cutout_svg.core.geometry import (
    point_in_polygon,
    rect_to_points,
    validate_polygon,
)
from batch_cutout_svg.core.image_loader import discover_images_in_folder, load_images_with_report
from batch_cutout_svg.core.mask import CutoutOptions, create_cutout_png
from batch_cutout_svg.core.naming import sanitize_filename_part, unique_path
from batch_cutout_svg.models.region import next_available_region_id
from batch_cutout_svg.ui.main_window import _coerce_dialog_paths, _translate_region
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


class ImageLoaderTests(unittest.TestCase):
    def test_file_dialog_tuple_paths_are_normalized(self) -> None:
        paths = _coerce_dialog_paths(("a.png", "b.JPG"))

        self.assertEqual([path.name for path in paths], ["a.png", "b.JPG"])
        self.assertTrue(all(path.is_absolute() for path in paths))

    def test_file_dialog_string_paths_use_tk_splitter(self) -> None:
        paths = _coerce_dialog_paths("a.png b.jpeg", lambda value: tuple(value.split()))

        self.assertEqual([path.name for path in paths], ["a.png", "b.jpeg"])

    def test_load_images_with_report_keeps_successful_images(self) -> None:
        tmp = make_test_dir()
        try:
            good = tmp / "good.png"
            bad = tmp / "bad.jpg"
            Image.new("RGB", (4, 4), (10, 20, 30)).save(good)
            bad.write_text("not an image", encoding="utf-8")

            result = load_images_with_report([good, bad])

            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].path, good)
            self.assertEqual(result.items[0].image.mode, "RGBA")
            self.assertEqual(len(result.failures), 1)
            self.assertEqual(result.failures[0].path, bad)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_discover_images_in_folder_finds_supported_images_only(self) -> None:
        tmp = make_test_dir()
        try:
            nested = tmp / "nested"
            nested.mkdir()
            first = tmp / "a.png"
            second = nested / "b.jpeg"
            ignored = nested / "notes.txt"
            Image.new("RGB", (2, 2)).save(first)
            Image.new("RGB", (2, 2)).save(second)
            ignored.write_text("x", encoding="utf-8")

            found = discover_images_in_folder(tmp)

            self.assertEqual(found, sorted([first, second], key=lambda item: str(item).lower()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RegionMoveTests(unittest.TestCase):
    def test_next_available_region_id_reuses_deleted_gap(self) -> None:
        region_id = next_available_region_id(
            ["region001", "region003", "region004", "region005", "region006"]
        )

        self.assertEqual(region_id, "region002")

    def test_translate_rect_region_updates_polygon_and_data(self) -> None:
        region = Region(
            id="region001",
            name="region001",
            shape_type="rect",
            data={"type": "rect", "x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0},
            polygon_points=rect_to_points(10.0, 20.0, 30.0, 40.0),
        )

        _translate_region(region, 5.0, -3.0)

        self.assertEqual(region.data["x"], 15.0)
        self.assertEqual(region.data["y"], 17.0)
        self.assertEqual(region.polygon_points, rect_to_points(15.0, 17.0, 30.0, 40.0))

    def test_translate_freehand_region_updates_data_points(self) -> None:
        region = Region(
            id="region001",
            name="region001",
            shape_type="freehand",
            data={"type": "freehand", "points": [(1.0, 2.0), (3.0, 4.0), (5.0, 2.0)]},
            polygon_points=[(1.0, 2.0), (3.0, 4.0), (5.0, 2.0)],
        )

        _translate_region(region, 2.0, 3.0)

        self.assertEqual(region.data["points"], [(3.0, 5.0), (5.0, 7.0), (7.0, 5.0)])
        self.assertEqual(region.polygon_points, [(3.0, 5.0), (5.0, 7.0), (7.0, 5.0)])


class MaskAndExporterTests(unittest.TestCase):
    def test_mask_has_transparent_background(self) -> None:
        image = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
        polygon = rect_to_points(5, 5, 10, 10)
        cutout = create_cutout_png(image, polygon, feather_radius=0)
        self.assertEqual(cutout.size, (10, 10))
        self.assertEqual(cutout.getpixel((5, 5))[3], 255)

    def test_boundary_connected_white_background_becomes_transparent(self) -> None:
        image = Image.new("RGBA", (20, 20), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, 13, 13), fill=(20, 20, 20, 255))

        cutout = create_cutout_png(
            image,
            rect_to_points(0, 0, 20, 20),
            options=CutoutOptions(feather_radius=0, remove_small_components=False),
        )

        self.assertEqual(cutout.getpixel((0, 0))[3], 0)
        self.assertEqual(cutout.getpixel((10, 10))[3], 255)

    def test_feather_does_not_leak_alpha_outside_user_region(self) -> None:
        image = Image.new("RGBA", (20, 20), (200, 0, 0, 255))

        cutout = create_cutout_png(
            image,
            [(0, 0), (20, 0), (0, 20)],
            options=CutoutOptions(feather_radius=2, remove_small_components=False),
        )

        self.assertEqual(cutout.getpixel((19, 19))[3], 0)

    def test_boundary_fill_preserves_enclosed_white_detail(self) -> None:
        image = Image.new("RGBA", (24, 24), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 18, 18), fill=(15, 15, 15, 255))
        draw.rectangle((10, 10, 13, 13), fill=(255, 255, 255, 255))

        cutout = create_cutout_png(
            image,
            rect_to_points(0, 0, 24, 24),
            options=CutoutOptions(feather_radius=0, remove_small_components=False),
        )

        self.assertEqual(cutout.getpixel((1, 1))[3], 0)
        self.assertEqual(cutout.getpixel((11, 11))[3], 255)

    def test_small_isolated_foreground_component_is_removed(self) -> None:
        image = Image.new("RGBA", (24, 24), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, 13, 13), fill=(20, 20, 20, 255))
        draw.point((20, 20), fill=(200, 0, 0, 255))

        cutout = create_cutout_png(
            image,
            rect_to_points(0, 0, 24, 24),
            options=CutoutOptions(
                feather_radius=0,
                remove_small_components=True,
                min_component_area=4,
            ),
        )

        self.assertEqual(cutout.getpixel((10, 10))[3], 255)
        self.assertEqual(cutout.getpixel((20, 20))[3], 0)

    def test_keep_largest_component_removes_other_foreground(self) -> None:
        image = Image.new("RGBA", (30, 20), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 12, 12), fill=(20, 20, 20, 255))
        draw.rectangle((22, 7, 25, 10), fill=(0, 80, 200, 255))

        cutout = create_cutout_png(
            image,
            rect_to_points(0, 0, 30, 20),
            options=CutoutOptions(
                feather_radius=0,
                remove_small_components=False,
                keep_largest_component=True,
            ),
        )

        self.assertEqual(cutout.getpixel((8, 8))[3], 255)
        self.assertEqual(cutout.getpixel((23, 8))[3], 0)

    def test_export_svg_embeds_png(self) -> None:
        tmp = make_test_dir()
        try:
            image = Image.new("RGBA", (20, 20), (255, 255, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((5, 5, 14, 14), fill=(0, 128, 255, 255))
            item = ImageItem(path=Path("sample.png"), image=image)
            region = Region(
                id="region001",
                name="part",
                shape_type="rect",
                data={},
                polygon_points=rect_to_points(0, 0, 20, 20),
            )
            output = export_region_as_svg(item, region, tmp / "out.svg", feather_radius=0)
            text = output.read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("data:image/png;base64,", text)
            encoded = text.split("data:image/png;base64,", 1)[1].split('"', 1)[0]
            embedded = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGBA")
            self.assertEqual(embedded.getpixel((0, 0))[3], 0)
            self.assertEqual(embedded.getpixel((10, 10))[3], 255)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
