from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .geometry import Point, bounding_box, normalize_points


@dataclass(frozen=True)
class CutoutOptions:
    feather_radius: float = 1.5
    white_threshold: int = 240
    near_white_tolerance: int = 15
    remove_small_components: bool = True
    min_component_area: int = 20
    keep_largest_component: bool = False


def create_cutout_png(
    image: Image.Image,
    polygon_points: list[Point],
    feather_radius: float = 1.5,
    options: CutoutOptions | None = None,
) -> Image.Image:
    options = options or CutoutOptions(feather_radius=feather_radius)
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

    user_region_mask = Image.new("L", roi.size, 0)
    draw = ImageDraw.Draw(user_region_mask)
    draw.polygon(local_points, fill=255)

    foreground_mask = _foreground_mask_from_boundary_fill(
        roi,
        user_region_mask,
        options,
    )
    base_alpha = roi.getchannel("A")
    combined_alpha = ImageChops.multiply(base_alpha, foreground_mask)
    combined_alpha = _clean_connected_components(combined_alpha, options)

    if options.feather_radius > 0:
        combined_alpha = combined_alpha.filter(
            ImageFilter.GaussianBlur(radius=float(options.feather_radius))
        )
        combined_alpha = ImageChops.multiply(combined_alpha, user_region_mask)

    roi.putalpha(combined_alpha)
    return roi


def _foreground_mask_from_boundary_fill(
    roi: Image.Image,
    user_region_mask: Image.Image,
    options: CutoutOptions,
) -> Image.Image:
    width, height = roi.size
    if width <= 0 or height <= 0:
        return Image.new("L", roi.size, 0)

    rgba = roi.convert("RGBA")
    image_pixels = rgba.load()
    region_pixels = user_region_mask.load()
    visited_background = bytearray(width * height)
    stack: list[tuple[int, int]] = []

    threshold = _clamp_int(options.white_threshold, 0, 255)
    tolerance = _clamp_int(options.near_white_tolerance, 0, 255)

    def index(x: int, y: int) -> int:
        return y * width + x

    def is_background_candidate(x: int, y: int) -> bool:
        if region_pixels[x, y] <= 0:
            return False
        r, g, b, a = image_pixels[x, y]
        return a <= 0 or _is_near_white(r, g, b, threshold, tolerance)

    def enqueue(x: int, y: int) -> None:
        pixel_index = index(x, y)
        if visited_background[pixel_index]:
            return
        if not is_background_candidate(x, y):
            return
        visited_background[pixel_index] = 1
        stack.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(1, height - 1):
        enqueue(0, y)
        enqueue(width - 1, y)

    while stack:
        x, y = stack.pop()
        if x > 0:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y > 0:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)

    foreground_mask = Image.new("L", roi.size, 0)
    foreground_pixels = foreground_mask.load()
    for y in range(height):
        for x in range(width):
            if region_pixels[x, y] > 0 and not visited_background[index(x, y)]:
                foreground_pixels[x, y] = region_pixels[x, y]
    return foreground_mask


def _is_near_white(
    red: int,
    green: int,
    blue: int,
    threshold: int,
    tolerance: int,
) -> bool:
    if red >= threshold and green >= threshold and blue >= threshold:
        return True
    near_white_floor = max(0, threshold - tolerance)
    return (
        min(red, green, blue) >= near_white_floor
        and max(red, green, blue) - min(red, green, blue) <= tolerance
    )


def _clean_connected_components(mask: Image.Image, options: CutoutOptions) -> Image.Image:
    if not options.remove_small_components and not options.keep_largest_component:
        return mask

    mask = mask.convert("L")
    width, height = mask.size
    pixels = mask.load()
    visited = bytearray(width * height)
    components: list[list[int]] = []

    def index(x: int, y: int) -> int:
        return y * width + x

    for y in range(height):
        for x in range(width):
            start_index = index(x, y)
            if visited[start_index] or pixels[x, y] <= 0:
                continue
            visited[start_index] = 1
            component: list[int] = []
            stack = [start_index]
            while stack:
                pixel_index = stack.pop()
                component.append(pixel_index)
                current_x = pixel_index % width
                current_y = pixel_index // width
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if not (0 <= next_x < width and 0 <= next_y < height):
                        continue
                    next_index = index(next_x, next_y)
                    if visited[next_index] or pixels[next_x, next_y] <= 0:
                        continue
                    visited[next_index] = 1
                    stack.append(next_index)
            components.append(component)

    if not components:
        return mask

    min_area = max(1, int(options.min_component_area))
    largest_index = max(range(len(components)), key=lambda item: len(components[item]))
    keep_indexes: set[int] = set()
    if options.keep_largest_component:
        keep_indexes.add(largest_index)
    else:
        for component_index, component in enumerate(components):
            if not options.remove_small_components or len(component) >= min_area:
                keep_indexes.add(component_index)
        if not keep_indexes:
            keep_indexes.add(largest_index)

    source_data = mask.tobytes()
    output_data = bytearray(len(source_data))
    for component_index in keep_indexes:
        for pixel_index in components[component_index]:
            output_data[pixel_index] = source_data[pixel_index]
    return Image.frombytes("L", mask.size, bytes(output_data))


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))

