"""Inbound media parsing and download helpers for Feishu."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from controlmesh.config import FeishuConfig
from controlmesh.files.image_processor import process_image
from controlmesh.files.prompt import MediaInfo
from controlmesh.files.prompt import build_media_prompt as _build_media_prompt_generic
from controlmesh.files.storage import prepare_destination as _prepare_destination
from controlmesh.files.storage import sanitize_filename as _sanitize_filename
from controlmesh.files.storage import update_index as _update_index
from controlmesh.files.tags import guess_mime

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import aiohttp

_CONTENT_DISPOSITION_RE = re.compile(
    r"""filename[*]?=(?:UTF-8'')?["']?([^"';\n]+)""",
    re.IGNORECASE,
)
_IMAGE_MESSAGE_TYPES = frozenset({"image"})
_VIDEO_MESSAGE_TYPES = frozenset({"media", "video"})
_FILE_MESSAGE_TYPES = frozenset({"file"})
_AUDIO_MESSAGE_TYPES = frozenset({"audio"})
_SUPPORTED_MEDIA_MESSAGE_TYPES = (
    _IMAGE_MESSAGE_TYPES | _VIDEO_MESSAGE_TYPES | _FILE_MESSAGE_TYPES | _AUDIO_MESSAGE_TYPES
)


@dataclass(frozen=True, slots=True)
class FeishuResourceDescriptor:
    """Metadata for one downloadable Feishu resource."""

    kind: Literal["image", "file", "audio", "video"]
    file_key: str
    file_name: str | None = None
    duration_ms: int | None = None
    cover_image_key: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedFeishuMessageContent:
    """Normalized Feishu message content."""

    text: str
    resources: list[FeishuResourceDescriptor]


@dataclass(frozen=True, slots=True)
class ResolveMediaRequest:
    """Parameters for turning one Feishu media message into local prompt text."""

    session: aiohttp.ClientSession
    config: FeishuConfig
    message_id: str
    message_type: str
    raw_content: object
    files_dir: Path
    workspace: Path
    tenant_access_token: str


@dataclass(frozen=True, slots=True)
class DownloadResourceRequest:
    """Parameters for downloading one Feishu message resource."""

    session: aiohttp.ClientSession
    config: FeishuConfig
    message_id: str
    resource: FeishuResourceDescriptor
    files_dir: Path
    tenant_access_token: str


def is_supported_media_message_type(message_type: str | None) -> bool:
    return bool(message_type and message_type in _SUPPORTED_MEDIA_MESSAGE_TYPES)


def parse_message_content(message_type: str, raw_content: object) -> ParsedFeishuMessageContent:
    """Parse a Feishu message content blob into text + resource descriptors."""
    content = _coerce_content_dict(raw_content)
    if message_type == "text":
        text = content.get("text")
        return ParsedFeishuMessageContent(
            text=text.strip() if isinstance(text, str) else "",
            resources=[],
        )
    parser = _resolve_parser(message_type)
    if parser is not None:
        return parser(content)

    if isinstance(raw_content, str):
        return ParsedFeishuMessageContent(text=raw_content.strip(), resources=[])
    return ParsedFeishuMessageContent(text="[unsupported message]", resources=[])


async def resolve_media_text(request: ResolveMediaRequest) -> str | None:
    """Download inbound media and return the prompt text for the orchestrator."""
    parsed = parse_message_content(request.message_type, request.raw_content)
    if not parsed.resources:
        return parsed.text or None

    await asyncio.to_thread(request.files_dir.mkdir, parents=True, exist_ok=True)
    info = await download_resource(
        DownloadResourceRequest(
            session=request.session,
            config=request.config,
            message_id=request.message_id,
            resource=parsed.resources[0],
            files_dir=request.files_dir,
            tenant_access_token=request.tenant_access_token,
        )
    )
    try:
        await asyncio.to_thread(_update_index, request.files_dir)
    except Exception:
        logger.warning("Failed to update Feishu media index", exc_info=True)
    return build_media_prompt(info, request.workspace)


async def download_resource(request: DownloadResourceRequest) -> MediaInfo:
    """Download one Feishu message resource into the local media directory."""
    resource = request.resource
    resource_type = "image" if resource.kind == "image" else "file"
    url = (
        f"{request.config.domain.rstrip('/')}/open-apis/im/v1/messages/"
        f"{request.message_id}/resources/{resource.file_key}"
    )
    headers = {"Authorization": f"Bearer {request.tenant_access_token}"}
    async with request.session.get(url, params={"type": resource_type}, headers=headers) as response:
        if response.status >= 400:
            body = await response.text()
            msg = (
                "Feishu resource download failed: "
                f"status={response.status} message_id={request.message_id} "
                f"file_key={resource.file_key} "
                f"body={body[:300]}"
            )
            raise RuntimeError(msg)
        payload = await response.read()
        content_type = response.headers.get("Content-Type") or ""
        disposition = (
            response.headers.get("Content-Disposition")
            or response.headers.get("content-disposition")
            or ""
        )

    file_name = _resolve_download_name(resource, content_type, disposition)
    destination = await asyncio.to_thread(_prepare_destination, request.files_dir, file_name)
    await asyncio.to_thread(destination.write_bytes, payload)
    logger.info("Downloaded Feishu %s -> %s", resource.kind, destination)

    if resource.kind == "image":
        destination = await asyncio.to_thread(process_image, destination)
        content_type = guess_mime(destination)
    elif not content_type:
        content_type = guess_mime(destination)

    return MediaInfo(
        path=destination,
        media_type=content_type or "application/octet-stream",
        file_name=destination.name,
        caption=None,
        original_type=_original_type(resource.kind),
    )


def build_media_prompt(info: MediaInfo, workspace: Path) -> str:
    """Build the Feishu-specific prompt for a downloaded media file."""
    return _build_media_prompt_generic(info, workspace, transport="Feishu")


def _coerce_content_dict(raw_content: object) -> dict[str, object]:
    if isinstance(raw_content, dict):
        return dict(raw_content)
    if not isinstance(raw_content, str):
        return {}
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        return {"text": raw_content}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _get_str(content: dict[str, object], key: str) -> str:
    value = content.get(key)
    return value.strip() if isinstance(value, str) else ""


def _get_int(content: dict[str, object], key: str) -> int | None:
    value = content.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _resolve_download_name(
    resource: FeishuResourceDescriptor,
    content_type: str,
    disposition: str,
) -> str:
    match = _CONTENT_DISPOSITION_RE.search(disposition)
    if match:
        return _sanitize_filename(match.group(1))
    if resource.file_name:
        return _sanitize_filename(resource.file_name)
    suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
    return _sanitize_filename(
        f"{resource.kind}_{resource.file_key}{suffix or _default_suffix(resource.kind)}"
    )


def _default_suffix(kind: str) -> str:
    return {
        "image": ".png",
        "audio": ".ogg",
        "video": ".mp4",
    }.get(kind, ".bin")


def _original_type(kind: str) -> str:
    return {
        "image": "photo",
        "audio": "audio",
        "video": "video",
    }.get(kind, "document")


def _resolve_parser(
    message_type: str,
) -> Callable[[dict[str, object]], ParsedFeishuMessageContent] | None:
    if message_type in _IMAGE_MESSAGE_TYPES:
        return _parse_image_content
    if message_type in _FILE_MESSAGE_TYPES:
        return _parse_file_content
    if message_type in _AUDIO_MESSAGE_TYPES:
        return _parse_audio_content
    if message_type in _VIDEO_MESSAGE_TYPES:
        return _parse_video_content
    return None


def _parse_image_content(content: dict[str, object]) -> ParsedFeishuMessageContent:
    image_key = _get_str(content, "image_key")
    if not image_key:
        return ParsedFeishuMessageContent(text="[image]", resources=[])
    return ParsedFeishuMessageContent(
        text=f"![image]({image_key})",
        resources=[FeishuResourceDescriptor(kind="image", file_key=image_key)],
    )


def _parse_file_content(content: dict[str, object]) -> ParsedFeishuMessageContent:
    file_key = _get_str(content, "file_key")
    file_name = _get_str(content, "file_name")
    if not file_key:
        return ParsedFeishuMessageContent(text="[file]", resources=[])
    name_attr = f' name="{file_name}"' if file_name else ""
    return ParsedFeishuMessageContent(
        text=f'<file key="{file_key}"{name_attr}/>',
        resources=[FeishuResourceDescriptor(kind="file", file_key=file_key, file_name=file_name or None)],
    )


def _parse_audio_content(content: dict[str, object]) -> ParsedFeishuMessageContent:
    file_key = _get_str(content, "file_key")
    duration_ms = _get_int(content, "duration")
    if not file_key:
        return ParsedFeishuMessageContent(text="[audio]", resources=[])
    duration_attr = f' duration="{duration_ms}"' if duration_ms is not None else ""
    return ParsedFeishuMessageContent(
        text=f'<audio key="{file_key}"{duration_attr}/>',
        resources=[FeishuResourceDescriptor(kind="audio", file_key=file_key, duration_ms=duration_ms)],
    )


def _parse_video_content(content: dict[str, object]) -> ParsedFeishuMessageContent:
    file_key = _get_str(content, "file_key")
    file_name = _get_str(content, "file_name")
    duration_ms = _get_int(content, "duration")
    cover_image_key = _get_str(content, "image_key")
    if not file_key:
        return ParsedFeishuMessageContent(text="[video]", resources=[])
    name_attr = f' name="{file_name}"' if file_name else ""
    duration_attr = f' duration="{duration_ms}"' if duration_ms is not None else ""
    return ParsedFeishuMessageContent(
        text=f'<video key="{file_key}"{name_attr}{duration_attr}/>',
        resources=[
            FeishuResourceDescriptor(
                kind="video",
                file_key=file_key,
                file_name=file_name or None,
                duration_ms=duration_ms,
                cover_image_key=cover_image_key or None,
            )
        ],
    )
