"""Read-only native history discovery and explicit session identity validation.

Viewer suggests candidates; the local OpenCode store is authoritative for identity.
No history text is promoted to a prompt, permission, or execution context here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

_SESSION_ID = re.compile(r"ses_[A-Za-z0-9]+\Z")


def opencode_store() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "opencode/opencode.db"


@dataclass(frozen=True, slots=True)
class NativeSessionRef:
    session_id: str
    directory: str
    project_id: str
    store_id: str
    revision: str
    model: str = ""
    title: str = ""
    source: str = "native-opencode"
    version: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> NativeSessionRef:
        if raw.get("version") != 1 or raw.get("source") not in {"native-opencode", "history-viewer"}:
            raise ValueError("Unsupported native session reference")
        names = ("session_id", "directory", "project_id", "store_id", "revision", "model", "title", "source")
        if any(not isinstance(raw.get(name), str) for name in names):
            raise ValueError("Invalid native session reference")
        ref = cls(
            session_id=str(raw["session_id"]), directory=str(raw["directory"]),
            project_id=str(raw["project_id"]), store_id=str(raw["store_id"]),
            revision=str(raw["revision"]), model=str(raw["model"]),
            title=str(raw["title"]), source=str(raw["source"]),
        )
        if not _SESSION_ID.fullmatch(ref.session_id) or not Path(ref.directory).is_absolute():
            raise ValueError("Invalid native session identity or directory")
        return ref


def read_native_session(session_id: str, *, source: str = "native-opencode") -> NativeSessionRef:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid OpenCode session ID")
    path = opencode_store().resolve()
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            row = db.execute(
                "SELECT id, directory, project_id, title, time_updated, time_archived FROM session WHERE id=?",
                (session_id,),
            ).fetchone()
            if row is None or row["time_archived"]:
                raise ValueError("Native session missing or archived")
            latest = db.execute(
                "SELECT id, time_updated, data FROM message WHERE session_id=? ORDER BY time_created DESC,id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            part_revision = db.execute(
                "SELECT count(*), max(time_updated) FROM part WHERE session_id=?", (session_id,),
            ).fetchone()
            model_row = db.execute(
                "SELECT data FROM message WHERE session_id=? AND json_extract(data,'$.role')='assistant' "
                "ORDER BY time_created DESC,id DESC LIMIT 1", (session_id,),
            ).fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise ValueError("Cannot read local OpenCode session store") from exc
    directory = Path(row["directory"])
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("Native session directory is unavailable")
    model_data = json.loads(model_row["data"]) if model_row else {}
    provider, model = model_data.get("providerID"), model_data.get("modelID")
    revision_data = [row["time_updated"], list(latest) if latest else None, list(part_revision)]
    return NativeSessionRef(
        session_id=session_id, directory=str(directory.resolve()), project_id=row["project_id"],
        store_id=hashlib.sha256(str(path).encode()).hexdigest(),
        revision=hashlib.sha256(json.dumps(revision_data, sort_keys=True).encode()).hexdigest(),
        model=f"{provider}/{model}" if provider and model else "", title=row["title"] or "", source=source,
    )


def validate_native_session(ref: NativeSessionRef, *, check_revision: bool = True) -> NativeSessionRef:
    current = read_native_session(ref.session_id, source=ref.source)
    if (current.directory, current.project_id, current.store_id) != (ref.directory, ref.project_id, ref.store_id):
        raise ValueError("Native session identity/directory/store changed; inspect again")
    if check_revision and current.revision != ref.revision:
        raise ValueError("Native session changed since inspection; inspect again before resuming")
    return current


def viewer_candidates(query: str, *, port: int = 8787, limit: int = 20) -> list[NativeSessionRef]:
    """Bounded loopback-only Viewer reads, with native-store identity cross-checks."""
    if not 1 <= port <= 65535 or not 1 <= limit <= 50:
        raise ValueError("Invalid Viewer port or limit")
    url = f"http://127.0.0.1:{port}/api/linux/opencode/sessions?" + urlencode({"q": query, "limit": limit})
    # Ignore proxies and reject redirects: a history server cannot redirect this read off-host.
    from urllib.request import HTTPRedirectHandler

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            return None

    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=5) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Viewer response too large")
        payload = json.loads(data)
        items = payload["sessions"]
        if not isinstance(items, list):
            raise ValueError("Invalid Viewer sessions response")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read History Viewer candidates") from exc
    refs = []
    for item in items[:limit]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        try:
            ref = read_native_session(item["id"], source="history-viewer")
        except ValueError:
            continue
        if not isinstance(item.get("cwd"), str) or str(Path(item["cwd"]).resolve()) != ref.directory:
            continue
        refs.append(ref)
    return refs


class NativeSessionLease:
    """Advisory exclusion between CM processes; native OpenCode clients do not honor it."""

    def __init__(self, ref: NativeSessionRef) -> None:
        import fcntl

        root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "controlmesh/native-sessions"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = hashlib.sha256(f"{ref.store_id}:{ref.session_id}".encode()).hexdigest()
        self._file = (root / f"{key}.lock").open("a")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            raise ValueError("Native session is already leased by another CM run") from exc

    def close(self) -> None:
        self._file.close()
