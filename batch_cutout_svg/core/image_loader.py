from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from batch_cutout_svg.models import ImageItem

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class ImageLoadFailure:
    path: Path
    reason: str


@dataclass(frozen=True)
class ImageLoadResult:
    items: list[ImageItem]
    failures: list[ImageLoadFailure]


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def discover_images_in_folder(folder: str | Path) -> list[Path]:
    root = Path(folder)
    try:
        if not root.exists():
            raise ValueError(f"文件夹不存在: {root}")
        if not root.is_dir():
            raise ValueError(f"不是文件夹: {root}")
    except OSError as exc:
        raise PermissionError(f"无法访问文件夹: {root}") from exc

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if _can_access(Path(dirpath) / dirname)
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            if is_supported_image(path):
                files.append(path)
    return sorted(files, key=lambda item: str(item).lower())


def load_image(path: str | Path) -> ImageItem:
    path = Path(path).expanduser()
    if not is_supported_image(path):
        raise ValueError(f"不支持的图片格式: {path}")
    try:
        if not path.exists():
            raise ValueError(f"图片不存在: {path}")
        if not path.is_file():
            raise ValueError(f"不是图片文件: {path}")
    except OSError as exc:
        raise PermissionError(f"无法访问图片: {path}") from exc
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA").copy()
    except PermissionError as exc:
        raise PermissionError(f"没有权限读取图片: {path}") from exc
    except OSError as exc:
        raise ValueError(f"无法读取图片或图片已损坏: {path} ({exc})") from exc
    return ImageItem(path=path, image=image)


def load_images(paths: list[str | Path]) -> list[ImageItem]:
    return [load_image(path) for path in paths]


def load_images_with_report(paths: list[str | Path]) -> ImageLoadResult:
    items: list[ImageItem] = []
    failures: list[ImageLoadFailure] = []
    for path_value in paths:
        path = Path(path_value).expanduser()
        try:
            items.append(load_image(path))
        except Exception as exc:  # noqa: BLE001 - report all failed paths to the UI.
            failures.append(ImageLoadFailure(path=path, reason=str(exc)))
    return ImageLoadResult(items=items, failures=failures)


def _can_access(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False
