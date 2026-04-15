from __future__ import annotations

from pathlib import Path

from PIL import Image

from controlmesh.files.image_processor import process_image


def _create_image(
    path: Path,
    size: tuple[int, int] = (100, 100),
    mode: str = "RGB",
    fmt: str = "JPEG",
) -> Path:
    img = Image.new(mode, size, color=(255, 0, 0) if mode == "RGB" else (255, 0, 0, 128))
    img.save(path, format=fmt)
    return path


def test_resize_large_jpeg(tmp_path: Path) -> None:
    src = _create_image(tmp_path / "big.jpg", size=(4000, 3000))
    result = process_image(src, max_dimension=2000)

    assert result.suffix == ".webp"
    with Image.open(result) as img:
        assert max(img.size) <= 2000


def test_convert_to_webp(tmp_path: Path) -> None:
    src = _create_image(tmp_path / "photo.jpg", size=(800, 600))
    result = process_image(src)

    assert result.suffix == ".webp"
    assert result.exists()
    assert not src.exists()


def test_skip_small_webp(tmp_path: Path) -> None:
    src = tmp_path / "small.webp"
    _create_image(src, size=(500, 500), fmt="WEBP")
    result = process_image(src)

    assert result == src
    assert result.exists()


def test_skip_gif(tmp_path: Path) -> None:
    src = tmp_path / "anim.gif"
    img = Image.new("P", (100, 100))
    img.save(src, format="GIF")

    result = process_image(src)
    assert result == src


def test_preserve_transparency(tmp_path: Path) -> None:
    src = _create_image(tmp_path / "alpha.png", size=(800, 600), mode="RGBA", fmt="PNG")
    result = process_image(src)

    assert result.suffix == ".webp"
    with Image.open(result) as img:
        assert img.mode == "RGBA"


def test_corrupt_image_returns_original(tmp_path: Path) -> None:
    src = tmp_path / "broken.jpg"
    src.write_bytes(b"not an image at all")

    result = process_image(src)
    assert result == src


def test_custom_settings(tmp_path: Path) -> None:
    src = _create_image(tmp_path / "photo.png", size=(3000, 2000), fmt="PNG")
    result = process_image(src, max_dimension=1000, output_format="png", quality=50)

    assert result.suffix == ".png"
    with Image.open(result) as img:
        assert max(img.size) <= 1000
