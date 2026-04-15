"""Incoming image processing: resize and convert to target format."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_MAX_DIMENSION = 2000
DEFAULT_QUALITY = 85
DEFAULT_FORMAT = "webp"

_SKIP_MIMES = frozenset({"image/gif", "image/apng"})


def process_image(
    path: Path,
    *,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    output_format: str = DEFAULT_FORMAT,
    quality: int = DEFAULT_QUALITY,
) -> Path:
    """Resize and convert an image. Returns new path (or original on error/skip)."""
    try:
        new_path = _do_process(path, max_dimension, output_format, quality)
    except Exception:
        logger.warning("Image processing failed for %s, using original", path, exc_info=True)
        return path
    else:
        logger.info("Processed image: %s -> %s", path.name, new_path.name)
        return new_path


def _do_process(path: Path, max_dimension: int, output_format: str, quality: int) -> Path:
    """Core processing logic. Raises on failure."""
    from controlmesh.files.tags import guess_mime

    mime = guess_mime(path)
    if not mime.startswith("image/") or mime in _SKIP_MIMES:
        return path

    with Image.open(path) as img:
        w, h = img.size
        needs_resize = max(w, h) > max_dimension
        is_target_format = path.suffix.lower() == f".{output_format}"

        if not needs_resize and is_target_format:
            return path

        result = img.copy()

    if needs_resize:
        ratio = max_dimension / max(w, h)
        new_size = (int(w * ratio), int(h * ratio))
        result = result.resize(new_size, Image.Resampling.LANCZOS)

    has_alpha = "A" in result.mode
    if output_format in ("webp", "png"):
        if result.mode not in ("RGB", "RGBA"):
            result = result.convert("RGBA" if has_alpha else "RGB")
    elif result.mode != "RGB":
        result = result.convert("RGB")

    new_path = path.with_suffix(f".{output_format}")
    if output_format in ("webp", "jpeg", "jpg"):
        result.save(new_path, quality=quality)
    else:
        result.save(new_path)

    if new_path != path:
        path.unlink(missing_ok=True)

    return new_path
