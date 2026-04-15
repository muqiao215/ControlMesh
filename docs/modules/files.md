# files/

Shared transport-agnostic file helpers used by Telegram, Matrix, and direct API paths.

## Files

- `files/allowed_roots.py`: `resolve_allowed_roots(file_access, workspace)`
- `files/tags.py`: file-tag parsing, MIME detection, media classification
- `files/storage.py`: filename sanitization + destination generation
- `files/prompt.py`: incoming-file prompt builder (`MediaInfo`, `build_media_prompt`)
- `files/image_processor.py`: incoming image resize and format conversion

## Purpose

Centralize file logic so Telegram, Matrix, and API use identical behavior for:

- `<file:...>` parsing
- MIME/type detection
- safe upload/download path handling
- incoming media prompt construction

## Core helpers

### `resolve_allowed_roots(...)`

Maps `file_access` to allowed roots:

- `all` -> unrestricted (`None`)
- `home` -> `[Path.home()]`
- `workspace` -> `[workspace]`
- unknown -> `[workspace]` fallback (restrictive)

### `sanitize_filename(name)`

- strips separators/unsafe chars
- normalizes repeated separators
- truncates long names
- fallback `"file"`

### `prepare_destination(base_dir, file_name)`

- uses date folder `YYYY-MM-DD`
- creates directories as needed
- de-duplicates via `_1`, `_2`, ... suffix

### `tags` helpers

- parse `<file:...>` tags and file URIs
- normalize Windows path variants
- detect MIME via `filetype` with extension fallback
- classify media as `photo|audio|video|document`

### `build_media_prompt(info, workspace, transport=...)`

Builds standardized `[INCOMING FILE]` prompt blocks for agent input.

### Image processing (`image_processor.py`)

`process_image(path, *, max_dimension, output_format, quality)` resizes and converts incoming images:

- images exceeding `max_dimension` (default 2000px) are proportionally resized using Lanczos resampling
- output is converted to the target format (default WebP) with configurable quality (default 85)
- animated formats (GIF, APNG) are skipped and returned as-is
- images already at or below the size limit and in the target format are returned unchanged
- on any processing error, the original file is used as fallback (non-fatal)

Configuration is driven by `config.image` (`ImageConfig`): `max_dimension`, `output_format`, `quality`.

Applied across all transports:

- Telegram: `messenger/telegram/media.py`
- Matrix: `messenger/matrix/media.py`
- API: `api/server.py` (upload endpoint)

## Integration points

- Telegram media ingest/send: `messenger/telegram/media.py`, `messenger/telegram/sender.py`, `messenger/telegram/app.py`
- Matrix media ingest: `messenger/matrix/media.py`, `messenger/matrix/bot.py`
- API upload/download and file-ref extraction: `api/server.py`
- API startup file-context wiring: `orchestrator/lifecycle.py`

## Runtime paths

- Telegram uploads: `~/.controlmesh/workspace/telegram_files/YYYY-MM-DD/`
- Matrix uploads: `~/.controlmesh/workspace/matrix_files/YYYY-MM-DD/`
- API uploads: `~/.controlmesh/workspace/api_files/YYYY-MM-DD/`
