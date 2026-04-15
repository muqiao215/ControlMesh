"""File path tag parsing, MIME detection, and file classification."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import filetype as _filetype

from controlmesh.infra.platform import is_windows

FILE_PATH_RE = re.compile(r"<file:([^>]+)>")

_SVG_SUFFIXES = frozenset({".svg", ".svgz"})
_RASTER_IMAGE_SUFFIXES = frozenset(
    {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".heic",
        ".heif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)


def extract_file_paths(text: str) -> list[str]:
    """Return all ``<file:/path>`` references from *text*."""
    return FILE_PATH_RE.findall(text)


def path_from_file_tag(file_tag: str) -> Path:
    """Convert one ``<file:...>`` payload to a local filesystem path.

    Handles plain paths and ``file:`` URIs. On Windows it normalizes
    drive-letter variants such as ``/C/...`` and ``/C:/...``.
    """
    value = file_tag.strip()
    if not value:
        return Path(value)

    parsed = urlparse(value)
    if parsed.scheme == "file":
        if parsed.netloc and parsed.path:
            # file://server/share/path or file://C:/Users/...
            value = f"//{parsed.netloc}{parsed.path}"
        elif parsed.netloc:
            value = f"//{parsed.netloc}"
        else:
            value = parsed.path or ""

    value = unquote(value)
    if is_windows():
        value = _normalize_windows_tag_path(value)
    return _resolve_container_path(Path(value))


def guess_mime(path: Path | str) -> str:
    """Guess MIME type using magic bytes first, then extension fallback.

    Uses the ``filetype`` library for binary format detection (images, audio,
    video, archives).  Falls back to ``mimetypes`` for text-based formats
    (source code, SVG, plain text) that lack magic byte signatures.
    """
    kind = _filetype.guess(str(path))
    if kind is not None:
        return str(kind.mime)
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def classify_mime(mime: str) -> str:
    """Classify a MIME type string into a category.

    Returns ``"photo"``, ``"audio"``, ``"video"``, or ``"document"``.
    """
    if mime.startswith("image/"):
        return "photo"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "document"


def is_image_path(path_str: str) -> bool:
    """Check if a file path points to a raster image based on extension/MIME.

    Uses extension-based detection only (no file access).  For content-based
    detection on files that exist on disk, use ``guess_mime`` instead.
    """
    suffix = Path(path_str).suffix.lower()
    if suffix in _SVG_SUFFIXES:
        return False
    if suffix in _RASTER_IMAGE_SUFFIXES:
        return True
    mime = mimetypes.guess_type(path_str)[0] or ""
    return mime.startswith("image/")


_DOCKER_MOUNT = "/controlmesh"


def _resolve_container_path(path: Path) -> Path:
    """Translate Docker container paths to host paths.

    Inside the sandbox container ``~/.controlmesh`` is mounted at ``/controlmesh``.
    CLI output references container-side paths like
    ``/controlmesh/workspace/output_to_user/file.png`` which don't exist on the
    host.  This rewrites them to the real host path.
    """
    try:
        relative = path.relative_to(_DOCKER_MOUNT)
    except ValueError:
        return path
    controlmesh_home = Path(
        os.environ.get("CONTROLMESH_HOME", str(Path.home() / ".controlmesh")),
    ).expanduser()
    return controlmesh_home / relative


def _normalize_windows_tag_path(value: str) -> str:
    """Normalize Windows drive-letter path variants from file tags."""
    path = value.replace("\\", "/")

    # file://C:/Users/... -> //C:/Users/... after URI parsing
    if len(path) >= 4 and path.startswith("//") and path[2].isalpha() and path[3] == ":":
        path = path[2:]

    # /C:/Users/... -> C:/Users/...
    if len(path) >= 3 and path[0] == "/" and path[1].isalpha() and path[2] == ":":
        return path[1:]

    # /C/Users/... -> C:/Users/...
    if (
        len(path) >= 2
        and path[0] == "/"
        and path[1].isalpha()
        and (len(path) == 2 or path[2] == "/")
    ):
        tail = path[2:]
        if not tail:
            tail = "/"
        elif not tail.startswith("/"):
            tail = f"/{tail}"
        return f"{path[1]}:{tail}"

    return path
