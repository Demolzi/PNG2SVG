from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .geometry import Point, bounding_box, normalize_points

CUTOUT_MODE_REGION = "region_only"
CUTOUT_MODE_BACKGROUND = "background_remove"
CUTOUT_MODE_GRABCUT = "grabcut"
TARGET_FILTER_OFF = "off"
TARGET_FILTER_LARGEST = "largest"
TARGET_FILTER_MAIN_WITH_NEIGHBORS = "main_with_neighbors"
TARGET_FILTER_SEED = "seed"


def _normalize_cutout_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized == CUTOUT_MODE_REGION:
        return CUTOUT_MODE_REGION
    if normalized == CUTOUT_MODE_GRABCUT:
        return CUTOUT_MODE_GRABCUT
    return CUTOUT_MODE_BACKGROUND


@dataclass(frozen=True)
class CutoutOptions:
    mode: str = CUTOUT_MODE_BACKGROUND
    feather_radius: float = 1.5
    white_threshold: int = 240
    near_white_tolerance: int = 15
    remove_small_components: bool = True
    min_component_area: int = 20
    keep_largest_component: bool = False
    target_filter_mode: str = TARGET_FILTER_MAIN_WITH_NEIGHBORS
    main_neighbor_distance: int = 20
    seed_point: tuple[int, int] | None = None
    edge_smooth_level: int = 2
    edge_feather_radius: float | None = None
    decontaminate_edge: bool = True
    decontaminate_alpha_min: int = 20
    decontaminate_alpha_max: int = 250
    defringe_strength: int = 1
    grabcut_iterations: int = 5
    grabcut_fallback_to_background: bool = True


@dataclass(frozen=True)
class Component:
    pixels: list[int]
    area: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]


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

    foreground_mask = _foreground_mask_for_mode(
        roi,
        user_region_mask,
        options,
    )
    if _normalize_cutout_mode(options.mode) != CUTOUT_MODE_REGION:
        foreground_mask = _clean_connected_components(foreground_mask, options)

    base_alpha = roi.getchannel("A")
    combined_alpha = ImageChops.multiply(base_alpha, foreground_mask)
    if _normalize_cutout_mode(options.mode) != CUTOUT_MODE_REGION:
        combined_alpha = filter_target_components(combined_alpha, options)
    combined_alpha = refine_alpha_mask(combined_alpha, user_region_mask, options)

    if options.decontaminate_edge and options.defringe_strength > 0:
        roi = _defringe_rgba(roi, combined_alpha, options)
    roi.putalpha(combined_alpha)
    return roi


def _foreground_mask_for_mode(
    roi: Image.Image,
    user_region_mask: Image.Image,
    options: CutoutOptions,
) -> Image.Image:
    mode = _normalize_cutout_mode(options.mode)
    if mode == CUTOUT_MODE_REGION:
        return user_region_mask.copy()
    if mode == CUTOUT_MODE_GRABCUT:
        return _foreground_mask_from_grabcut(roi, user_region_mask, options)
    return _foreground_mask_from_boundary_fill(roi, user_region_mask, options)


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
    boundary_background = _sample_boundary_background_color(
        rgba,
        user_region_mask,
        threshold,
        tolerance,
    )

    def index(x: int, y: int) -> int:
        return y * width + x

    def is_background_candidate(x: int, y: int) -> bool:
        if region_pixels[x, y] <= 0:
            return False
        r, g, b, a = image_pixels[x, y]
        return a <= 0 or _is_near_white(
            r,
            g,
            b,
            threshold,
            tolerance,
            boundary_background,
        )

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


def _foreground_mask_from_grabcut(
    roi: Image.Image,
    user_region_mask: Image.Image,
    options: CutoutOptions,
) -> Image.Image:
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np
    except ImportError:
        return _grabcut_fallback_mask(roi, user_region_mask, options)

    width, height = roi.size
    if width <= 1 or height <= 1:
        return _grabcut_fallback_mask(roi, user_region_mask, options)

    rgba = roi.convert("RGBA")
    rgb_array = np.asarray(rgba.convert("RGB"), dtype=np.uint8).copy()
    alpha_array = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    region_array = np.asarray(user_region_mask.convert("L"), dtype=np.uint8) > 0
    region_area = int(region_array.sum())
    if region_area <= 0:
        return Image.new("L", roi.size, 0)

    grabcut_mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    grabcut_mask[region_array] = cv2.GC_PR_FGD
    grabcut_mask[alpha_array <= 0] = cv2.GC_BGD

    fallback_foreground = _foreground_mask_from_boundary_fill(roi, user_region_mask, options)
    fallback_array = np.asarray(fallback_foreground.convert("L"), dtype=np.uint8) > 0
    fallback_area = int(fallback_array.sum())
    if 0 < fallback_area < region_area * 0.95:
        grabcut_mask[fallback_array] = cv2.GC_FGD
        grabcut_mask[region_array & ~fallback_array] = cv2.GC_BGD
    else:
        seed_array = _central_seed_array(region_array)
        if int(seed_array.sum()) > 0:
            grabcut_mask[seed_array] = cv2.GC_FGD

    _mark_roi_boundary_background(grabcut_mask, region_array, cv2.GC_BGD)
    if not _has_grabcut_class(grabcut_mask, cv2.GC_FGD):
        seed_array = _central_seed_array(region_array)
        if int(seed_array.sum()) <= 0:
            return _grabcut_fallback_mask(roi, user_region_mask, options)
        grabcut_mask[seed_array] = cv2.GC_FGD
    if not _has_grabcut_background(grabcut_mask, cv2):
        return _grabcut_fallback_mask(roi, user_region_mask, options)

    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(
            rgb_array,
            grabcut_mask,
            None,
            bgd_model,
            fgd_model,
            max(1, int(options.grabcut_iterations)),
            cv2.GC_INIT_WITH_MASK,
        )
    except Exception:
        return _grabcut_fallback_mask(roi, user_region_mask, options)

    output_array = (
        ((grabcut_mask == cv2.GC_FGD) | (grabcut_mask == cv2.GC_PR_FGD))
        & region_array
    )
    output_area = int(output_array.sum())
    if _grabcut_result_failed(output_area, region_area):
        return _grabcut_fallback_mask(roi, user_region_mask, options)
    return Image.frombytes("L", roi.size, (output_array.astype(np.uint8) * 255).tobytes())


def _grabcut_fallback_mask(
    roi: Image.Image,
    user_region_mask: Image.Image,
    options: CutoutOptions,
) -> Image.Image:
    if options.grabcut_fallback_to_background:
        return _foreground_mask_from_boundary_fill(roi, user_region_mask, options)
    return user_region_mask.copy()


def _central_seed_array(region_array):
    try:
        import numpy as np
    except ImportError:
        return region_array
    ys, xs = np.where(region_array)
    if len(xs) == 0 or len(ys) == 0:
        return np.zeros_like(region_array, dtype=bool)
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max())
    width = right - left + 1
    height = bottom - top + 1
    seed_left = left + max(0, round(width * 0.3))
    seed_right = right - max(0, round(width * 0.3))
    seed_top = top + max(0, round(height * 0.3))
    seed_bottom = bottom - max(0, round(height * 0.3))
    if seed_right < seed_left or seed_bottom < seed_top:
        seed_left, seed_right = left, right
        seed_top, seed_bottom = top, bottom
    seed = np.zeros_like(region_array, dtype=bool)
    seed[seed_top : seed_bottom + 1, seed_left : seed_right + 1] = True
    return seed & region_array


def _mark_roi_boundary_background(grabcut_mask, region_array, background_value: int) -> None:
    height, width = region_array.shape
    if width <= 0 or height <= 0:
        return
    grabcut_mask[0, region_array[0, :]] = background_value
    grabcut_mask[height - 1, region_array[height - 1, :]] = background_value
    grabcut_mask[region_array[:, 0], 0] = background_value
    grabcut_mask[region_array[:, width - 1], width - 1] = background_value


def _has_grabcut_class(grabcut_mask, value: int) -> bool:
    try:
        import numpy as np
    except ImportError:
        return False
    return bool(np.any(grabcut_mask == value))


def _has_grabcut_background(grabcut_mask, cv2_module) -> bool:
    try:
        import numpy as np
    except ImportError:
        return False
    return bool(
        np.any(grabcut_mask == cv2_module.GC_BGD)
        or np.any(grabcut_mask == cv2_module.GC_PR_BGD)
    )


def _grabcut_result_failed(foreground_area: int, region_area: int) -> bool:
    if region_area <= 0:
        return True
    ratio = foreground_area / region_area
    return ratio < 0.01 or ratio > 0.95


def _is_near_white(
    red: int,
    green: int,
    blue: int,
    threshold: int,
    tolerance: int,
    background_sample: tuple[int, int, int] | None = None,
) -> bool:
    if red >= threshold and green >= threshold and blue >= threshold:
        return True
    near_white_floor = max(0, threshold - tolerance)
    if (
        min(red, green, blue) >= near_white_floor
        and max(red, green, blue) - min(red, green, blue) <= tolerance
    ):
        return True
    if _is_light_low_chroma(red, green, blue, threshold, tolerance):
        return True
    if background_sample is not None and max(red, green, blue) >= near_white_floor:
        distance_limit = max(12.0, float(tolerance) * 1.8)
        return _color_distance((red, green, blue), background_sample) <= distance_limit
    return False


def _is_light_low_chroma(
    red: int,
    green: int,
    blue: int,
    threshold: int,
    tolerance: int,
) -> bool:
    value = max(red, green, blue)
    spread = value - min(red, green, blue)
    if value < threshold:
        return False
    return spread <= max(18, tolerance * 2)


def _sample_boundary_background_color(
    rgba: Image.Image,
    user_region_mask: Image.Image,
    threshold: int,
    tolerance: int,
) -> tuple[int, int, int] | None:
    width, height = rgba.size
    if width <= 0 or height <= 0:
        return None

    image_pixels = rgba.load()
    region_pixels = user_region_mask.load()
    samples: list[tuple[int, int, int]] = []

    def add_sample(x: int, y: int) -> None:
        if region_pixels[x, y] <= 0:
            return
        red, green, blue, alpha = image_pixels[x, y]
        if alpha <= 0:
            return
        if (
            red >= threshold
            and green >= threshold
            and blue >= threshold
        ) or _is_light_low_chroma(red, green, blue, threshold, tolerance):
            samples.append((red, green, blue))

    for x in range(width):
        add_sample(x, 0)
        add_sample(x, height - 1)
    for y in range(1, height - 1):
        add_sample(0, y)
        add_sample(width - 1, y)

    if not samples:
        return None
    count = len(samples)
    return (
        round(sum(sample[0] for sample in samples) / count),
        round(sum(sample[1] for sample in samples) / count),
        round(sum(sample[2] for sample in samples) / count),
    )


def _color_distance(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
) -> float:
    return math.sqrt(
        (first[0] - second[0]) ** 2
        + (first[1] - second[1]) ** 2
        + (first[2] - second[2]) ** 2
    )


def filter_target_components(mask: Image.Image, options: CutoutOptions) -> Image.Image:
    mode = _normalize_target_filter_mode(options.target_filter_mode)
    if options.keep_largest_component:
        mode = TARGET_FILTER_LARGEST
    if mode == TARGET_FILTER_OFF:
        return mask

    mask = mask.convert("L")
    components = find_connected_components(mask)
    if not components:
        return mask

    main_component = _select_main_component(components, mask.size, options)
    if main_component is None:
        main_component = max(components, key=lambda component: component.area)

    if mode in {TARGET_FILTER_LARGEST, TARGET_FILTER_SEED}:
        keep_components = [main_component]
    else:
        min_area = max(1, int(options.min_component_area))
        neighbor_distance = _effective_main_neighbor_distance(options, mask.size)
        keep_components = [
            component
            for component in components
            if component is main_component
            or (
                component.area >= min_area
                and _bbox_distance(component.bbox, main_component.bbox) <= neighbor_distance
            )
        ]

    return _mask_from_components(mask, keep_components)


def find_connected_components(mask: Image.Image) -> list[Component]:
    mask = mask.convert("L")
    width, height = mask.size
    pixels = mask.load()
    visited = bytearray(width * height)
    components: list[Component] = []

    def index(x: int, y: int) -> int:
        return y * width + x

    for y in range(height):
        for x in range(width):
            start_index = index(x, y)
            if visited[start_index] or pixels[x, y] <= 0:
                continue
            visited[start_index] = 1
            component_pixels: list[int] = []
            stack = [start_index]
            min_x = max_x = x
            min_y = max_y = y
            x_total = 0
            y_total = 0
            while stack:
                pixel_index = stack.pop()
                component_pixels.append(pixel_index)
                current_x = pixel_index % width
                current_y = pixel_index // width
                min_x = min(min_x, current_x)
                max_x = max(max_x, current_x)
                min_y = min(min_y, current_y)
                max_y = max(max_y, current_y)
                x_total += current_x
                y_total += current_y
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
            area = len(component_pixels)
            components.append(
                Component(
                    pixels=component_pixels,
                    area=area,
                    bbox=(min_x, min_y, max_x + 1, max_y + 1),
                    centroid=(x_total / area, y_total / area),
                )
            )
    return components


def _select_main_component(
    components: list[Component],
    size: tuple[int, int],
    options: CutoutOptions,
) -> Component | None:
    mode = _normalize_target_filter_mode(options.target_filter_mode)
    if mode == TARGET_FILTER_SEED and options.seed_point is not None:
        seed_x, seed_y = options.seed_point
        width, height = size
        if 0 <= seed_x < width and 0 <= seed_y < height:
            seed_index = int(seed_y) * width + int(seed_x)
            for component in components:
                if seed_index in component.pixels:
                    return component
    return max(components, key=lambda component: component.area)


def _mask_from_components(mask: Image.Image, components: list[Component]) -> Image.Image:
    source_data = mask.tobytes()
    output_data = bytearray(len(source_data))
    for component in components:
        for pixel_index in component.pixels:
            output_data[pixel_index] = source_data[pixel_index]
    return Image.frombytes("L", mask.size, bytes(output_data))


def _bbox_distance(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    first_left, first_top, first_right, first_bottom = first
    second_left, second_top, second_right, second_bottom = second
    dx = max(second_left - first_right, first_left - second_right, 0)
    dy = max(second_top - first_bottom, first_top - second_bottom, 0)
    return math.hypot(dx, dy)


def _effective_main_neighbor_distance(
    options: CutoutOptions,
    size: tuple[int, int],
) -> float:
    configured = int(options.main_neighbor_distance)
    if configured > 0:
        return float(configured)
    width, height = size
    return float(max(15, min(40, round(min(width, height) * 0.03))))


def _normalize_target_filter_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {
        TARGET_FILTER_OFF,
        TARGET_FILTER_LARGEST,
        TARGET_FILTER_MAIN_WITH_NEIGHBORS,
        TARGET_FILTER_SEED,
    }:
        return normalized
    return TARGET_FILTER_MAIN_WITH_NEIGHBORS


def refine_alpha_mask(
    mask: Image.Image,
    user_region_mask: Image.Image,
    options: CutoutOptions,
) -> Image.Image:
    result = mask.convert("L")
    original = result
    smooth_level = _clamp_int(options.edge_smooth_level, 0, 3)

    if smooth_level >= 1:
        result = _close_mask(result, 3)
    if smooth_level >= 2:
        result = _open_mask(result, 3)
    if smooth_level >= 3:
        result = _close_mask(result, 5)
    if result.getbbox() is None:
        result = original

    feather_radius = _effective_edge_feather_radius(options, result.size)
    if feather_radius > 0:
        result = result.filter(ImageFilter.GaussianBlur(radius=feather_radius))
    return ImageChops.multiply(result, user_region_mask)


def _close_mask(mask: Image.Image, size: int) -> Image.Image:
    return mask.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))


def _open_mask(mask: Image.Image, size: int) -> Image.Image:
    return mask.filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))


def _effective_edge_feather_radius(options: CutoutOptions, size: tuple[int, int]) -> float:
    if options.edge_feather_radius is None:
        radius = min(max(0.0, float(options.feather_radius)), 0.7)
    else:
        radius = max(0.0, float(options.edge_feather_radius))
    return _effective_feather_radius(radius, size)


def _effective_feather_radius(radius: float, size: tuple[int, int]) -> float:
    radius = max(0.0, float(radius))
    if radius <= 0:
        return 0.0
    width, height = size
    smallest_side = min(width, height)
    if smallest_side <= 0:
        return 0.0
    return min(radius, max(0.0, smallest_side / 12.0))


def _defringe_rgba(
    roi: Image.Image,
    alpha: Image.Image,
    options: CutoutOptions,
) -> Image.Image:
    strength = _clamp_int(options.defringe_strength, 0, 3)
    if strength <= 0:
        return roi

    source = roi.convert("RGBA")
    width, height = source.size
    if width <= 0 or height <= 0:
        return source

    source_pixels = source.load()
    alpha_pixels = alpha.load()
    output = source.copy()
    output_pixels = output.load()
    threshold = _clamp_int(options.white_threshold, 0, 255)
    tolerance = _clamp_int(options.near_white_tolerance, 0, 255)
    alpha_min = _clamp_int(options.decontaminate_alpha_min, 0, 255)
    alpha_max = _clamp_int(options.decontaminate_alpha_max, 0, 255)
    if alpha_max <= alpha_min:
        alpha_min, alpha_max = 20, 250
    sample_radius = 1 + strength
    blend = min(1.0, 0.35 + strength * 0.2)

    for y in range(height):
        for x in range(width):
            current_alpha = alpha_pixels[x, y]
            if not (alpha_min < current_alpha < alpha_max):
                continue
            red, green, blue, source_alpha = source_pixels[x, y]
            if not _is_near_white(red, green, blue, threshold, tolerance):
                continue

            replacement = _replacement_foreground_color(
                source_pixels,
                alpha_pixels,
                width,
                height,
                x,
                y,
                sample_radius,
                threshold,
                tolerance,
            )
            if replacement is None:
                continue
            output_pixels[x, y] = (
                round(red * (1.0 - blend) + replacement[0] * blend),
                round(green * (1.0 - blend) + replacement[1] * blend),
                round(blue * (1.0 - blend) + replacement[2] * blend),
                source_alpha,
            )
    return output


def _replacement_foreground_color(
    source_pixels,
    alpha_pixels,
    width: int,
    height: int,
    x: int,
    y: int,
    radius: int,
    threshold: int,
    tolerance: int,
) -> tuple[int, int, int] | None:
    total_weight = 0.0
    red_total = 0.0
    green_total = 0.0
    blue_total = 0.0
    for next_y in range(max(0, y - radius), min(height, y + radius + 1)):
        for next_x in range(max(0, x - radius), min(width, x + radius + 1)):
            if next_x == x and next_y == y:
                continue
            neighbor_alpha = alpha_pixels[next_x, next_y]
            if neighbor_alpha < 220:
                continue
            red, green, blue, _source_alpha = source_pixels[next_x, next_y]
            if _is_near_white(red, green, blue, threshold, tolerance):
                continue
            distance = abs(next_x - x) + abs(next_y - y)
            weight = float(neighbor_alpha) / max(1, distance)
            total_weight += weight
            red_total += red * weight
            green_total += green * weight
            blue_total += blue * weight
    if total_weight <= 0:
        return None
    return (
        round(red_total / total_weight),
        round(green_total / total_weight),
        round(blue_total / total_weight),
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

