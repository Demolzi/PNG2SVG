from __future__ import annotations

from pathlib import Path

from PIL import Image

from batch_cutout_svg.models import ImageItem

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def discover_images_in_folder(folder: str | Path) -> list[Path]:
    root = Path(folder)
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and is_supported_image(path)
    ]
    return sorted(files, key=lambda item: str(item).lower())


def load_image(path: str | Path) -> ImageItem:
    path = Path(path)
    if not is_supported_image(path):
        raise ValueError(f"不支持的图片格式: {path}")
    with Image.open(path) as source:
        image = source.convert("RGBA").copy()
    return ImageItem(path=path, image=image)


def load_images(paths: list[str | Path]) -> list[ImageItem]:
    return [load_image(path) for path in paths if is_supported_image(path)]

