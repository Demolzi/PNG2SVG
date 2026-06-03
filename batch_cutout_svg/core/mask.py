from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .geometry import Point, bounding_box, normalize_points


def create_cutout_png(
    image: Image.Image,
    polygon_points: list[Point],
    feather_radius: float = 1.5,
) -> Image.Image:
    points = normalize_points(polygon_points)
    if len(points) < 3:
        raise ValueError("区域点数不足，无法生成抠图。")

    left, top, right, bottom = bounding_box(points)
    left_i = max(0, math.floor(left))
    top_i = max(0, math.floor(top))
    right_i = min(image.width, math.ceil(right))
    bottom_i = min(image.height, math.ceil(bottom))
    if right_i <= left_i or bottom_i <= top_i:
        raise ValueError("区域外接矩形为空，无法生成抠图。")

    source = image.convert("RGBA")
    roi = source.crop((left_i, top_i, right_i, bottom_i))
    local_points = [(x - left_i, y - top_i) for x, y in points]

    mask = Image.new("L", roi.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(local_points, fill=255)
    if feather_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=float(feather_radius)))

    base_alpha = roi.getchannel("A")
    combined_alpha = ImageChops.multiply(base_alpha, mask)
    roi.putalpha(combined_alpha)
    return roi

