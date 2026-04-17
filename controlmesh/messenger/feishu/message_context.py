"""Feishu inbound message content and context helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from controlmesh.integrations.feishu_auth_kit import parse_feishu_auth_kit_message_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedFeishuContent:
    """Normalized text plus shallow semantic hints from a Feishu message."""

    text: str
    message_type: str
    post_title: str | None = None
    quote_summary: str | None = None


def extract_feishu_content_from_event(
    payload: dict[str, Any],
    message_type: str,
    raw_content: object,
) -> ParsedFeishuContent:
    """Prefer feishu-auth-kit message context, then enrich with CM-only semantics."""
    fallback = extract_feishu_content(message_type, raw_content)
    kit_context = _parse_auth_kit_context(payload)
    if not kit_context:
        return fallback
    kit_text = _kit_prompt_text(kit_context)
    if message_type == "text" and kit_text:
        return ParsedFeishuContent(
            text=kit_text,
            message_type=message_type,
            quote_summary=fallback.quote_summary,
        )
    return fallback


def extract_feishu_content(message_type: str, raw_content: object) -> ParsedFeishuContent:
    """Extract agent-readable text from Feishu text/post/card content."""
    if message_type == "text":
        parsed = _parse_json(raw_content)
        text = _extract_text_value(parsed, raw_content)
        return ParsedFeishuContent(
            text=text,
            message_type=message_type,
            quote_summary=_extract_quote_summary(parsed),
        )
    if message_type == "post":
        parsed = _parse_json(raw_content)
        text, title = _extract_post(parsed)
        return ParsedFeishuContent(
            text=text,
            message_type=message_type,
            post_title=title,
            quote_summary=_extract_quote_summary(parsed),
        )
    if message_type == "interactive":
        parsed = _parse_json(raw_content)
        text = _extract_interactive_text(parsed) or "[interactive card]"
        return ParsedFeishuContent(
            text=text,
            message_type=message_type,
            quote_summary=_extract_quote_summary(parsed),
        )
    if message_type == "merge_forward":
        parsed = _parse_json(raw_content)
        title = _first_string(parsed, ("title", "summary"))
        text = f"[merge_forward] {title}" if title else "[merge_forward message]"
        return ParsedFeishuContent(
            text=text,
            message_type=message_type,
            post_title=title,
            quote_summary=_extract_quote_summary(parsed),
        )
    return ParsedFeishuContent(text="", message_type=message_type)


def build_feishu_agent_input(message: Any) -> str:
    """Build the text sent to the agent, preserving first-order Feishu context."""
    context_lines: list[str] = []
    message_type = str(getattr(message, "message_type", "text") or "text")
    if message_type != "text":
        context_lines.append(f"message_type={message_type}")
    post_title = getattr(message, "post_title", None)
    if post_title:
        context_lines.append(f"post_title={post_title}")
    thread_id = getattr(message, "thread_id", None)
    if thread_id:
        context_lines.append(f"thread_id={thread_id}")
    root_id = getattr(message, "root_id", None)
    if root_id:
        context_lines.append(f"root_message_id={root_id}")
    parent_id = getattr(message, "parent_id", None)
    if parent_id:
        context_lines.append(f"parent_message_id={parent_id}")
    quote_summary = getattr(message, "quote_summary", None)
    if quote_summary:
        context_lines.append(f"quote_summary={quote_summary}")

    text = str(getattr(message, "text", "") or "")
    if not context_lines:
        return text
    return (
        "[Feishu inbound context]\n"
        f"{chr(10).join(context_lines)}\n"
        "[/Feishu inbound context]\n\n"
        f"{text}"
    )


def _parse_json(raw_content: object) -> object:
    if isinstance(raw_content, (dict, list)):
        return raw_content
    if not isinstance(raw_content, str):
        return None
    try:
        return json.loads(raw_content)
    except json.JSONDecodeError:
        return raw_content.strip()


def _extract_text_value(parsed: object, raw_content: object) -> str:
    if isinstance(parsed, dict):
        value = parsed.get("text")
        return value.strip() if isinstance(value, str) else ""
    if isinstance(parsed, str):
        return parsed.strip()
    if isinstance(raw_content, dict):
        value = raw_content.get("text")
        return value.strip() if isinstance(value, str) else ""
    return ""


def _extract_post(parsed: object) -> tuple[str, str | None]:
    if not isinstance(parsed, dict):
        return "[rich text message]", None
    body = _unwrap_post_locale(parsed)
    if body is None:
        return "[rich text message]", None
    title = body.get("title") if isinstance(body.get("title"), str) else None
    lines: list[str] = []
    if title:
        lines.extend([f"**{title}**", ""])
    content = body.get("content")
    if isinstance(content, list):
        for paragraph in content:
            if not isinstance(paragraph, list):
                continue
            line = "".join(_render_post_element(item) for item in paragraph if isinstance(item, dict))
            if line:
                lines.append(line)
    return "\n".join(lines).strip() or "[rich text message]", title


def _unwrap_post_locale(parsed: dict[str, Any]) -> dict[str, Any] | None:
    if "title" in parsed or "content" in parsed:
        return parsed
    for locale in ("zh_cn", "en_us", "ja_jp"):
        value = parsed.get(locale)
        if isinstance(value, dict):
            return value
    for value in parsed.values():
        if isinstance(value, dict):
            return value
    return None


def _render_post_element(item: dict[str, Any]) -> str:  # noqa: PLR0911 - mirrors Feishu tag variants.
    tag = item.get("tag")
    if tag == "text":
        return _styled_text(str(item.get("text") or ""), item.get("style"))
    if tag == "a":
        text = str(item.get("text") or item.get("href") or "")
        href = str(item.get("href") or "")
        return f"[{text}]({href})" if href else text
    if tag == "at":
        if item.get("user_id") == "all":
            return "@all"
        return f"@{item.get('user_name') or item.get('user_id') or 'user'}"
    if tag == "img":
        image_key = str(item.get("image_key") or "")
        return f"![image]({image_key})" if image_key else ""
    if tag == "media":
        file_key = str(item.get("file_key") or "")
        return f'<file key="{file_key}"/>' if file_key else ""
    if tag == "code_block":
        lang = str(item.get("language") or "")
        code = str(item.get("text") or "")
        return f"\n```{lang}\n{code}\n```\n"
    if tag == "hr":
        return "\n---\n"
    return str(item.get("text") or "")


def _styled_text(text: str, style: object) -> str:
    if not isinstance(style, list):
        return text
    result = text
    if "bold" in style:
        result = f"**{result}**"
    if "italic" in style:
        result = f"*{result}*"
    if "lineThrough" in style:
        result = f"~~{result}~~"
    if "codeInline" in style:
        result = f"`{result}`"
    return result


def _extract_interactive_text(parsed: object) -> str:
    values: list[str] = []
    _collect_interactive_text(parsed, values)
    deduped = list(dict.fromkeys(item.strip() for item in values if item.strip()))
    return "\n".join(deduped[:20]).strip()


def _collect_interactive_text(value: object, values: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content", "title"} and isinstance(item, str):
                values.append(item)
            else:
                _collect_interactive_text(item, values)
    elif isinstance(value, list):
        for item in value:
            _collect_interactive_text(item, values)


def _extract_quote_summary(parsed: object) -> str | None:
    summary = _find_quote_value(parsed)
    if not summary:
        return None
    return summary[:240]


def _find_quote_value(value: object) -> str | None:
    quote_keys = {"quote", "quoted", "quoted_text", "quote_text", "quoted_content", "reply_to"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in quote_keys:
                text = _value_to_text(item)
                if text:
                    return text
            nested = _find_quote_value(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_quote_value(item)
            if nested:
                return nested
    return None


def _value_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        direct = _first_string(value, ("text", "content", "title", "summary"))
        if direct:
            return direct
        if "content" in value:
            text, _title = _extract_post(value)
            return "" if text == "[rich text message]" else text
    if isinstance(value, list):
        parts = [_value_to_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return ""


def _first_string(value: object, keys: tuple[str, ...]) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _parse_auth_kit_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        context = parse_feishu_auth_kit_message_context(payload)
    except Exception:
        logger.debug("feishu-auth-kit parse-inbound unavailable, falling back", exc_info=True)
        return None
    return context if isinstance(context, dict) else None


def _kit_prompt_text(context: dict[str, Any]) -> str:
    prompt_text = context.get("prompt_text")
    if isinstance(prompt_text, str) and prompt_text.strip():
        return prompt_text.strip()
    text = context.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""
