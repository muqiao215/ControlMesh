"""Tests for update observer, upgrade execution, and sentinel lifecycle."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from controlmesh.infra.updater import (
    UpdateObserver,
    consume_upgrade_sentinel,
    perform_upgrade_pipeline,
    write_upgrade_sentinel,
)
from controlmesh.infra.version import VersionInfo

# ---------------------------------------------------------------------------
# Upgrade Sentinel
# ---------------------------------------------------------------------------


class TestUpgradeSentinel:
    """Test sentinel write/read/delete lifecycle."""

    def test_write_and_consume(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=42, old_version="1.0.0", new_version="2.0.0")
        sentinel_file = tmp_path / "upgrade-sentinel.json"
        assert sentinel_file.exists()

        data = consume_upgrade_sentinel(tmp_path)
        assert data is not None
        assert data["chat_id"] == 42
        assert data["old_version"] == "1.0.0"
        assert data["new_version"] == "2.0.0"

        # File should be deleted after consumption
        assert not sentinel_file.exists()

    def test_consume_returns_none_when_absent(self, tmp_path: Path) -> None:
        assert consume_upgrade_sentinel(tmp_path) is None

    def test_consume_deletes_corrupt_file(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "upgrade-sentinel.json"
        sentinel.write_text("not valid json{{{", encoding="utf-8")

        result = consume_upgrade_sentinel(tmp_path)
        assert result is None
        assert not sentinel.exists()

    def test_write_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "dir"
        write_upgrade_sentinel(nested, chat_id=1, old_version="0.1", new_version="0.2")
        assert (nested / "upgrade-sentinel.json").exists()

    def test_double_consume_returns_none(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=1, old_version="1.0", new_version="2.0")
        first = consume_upgrade_sentinel(tmp_path)
        second = consume_upgrade_sentinel(tmp_path)
        assert first is not None
        assert second is None

    def test_sentinel_content_is_valid_json(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(tmp_path, chat_id=99, old_version="1.0.0", new_version="1.1.0")
        raw = (tmp_path / "upgrade-sentinel.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data == {"chat_id": 99, "old_version": "1.0.0", "new_version": "1.1.0"}

    def test_transport_mismatch_does_not_consume(self, tmp_path: Path) -> None:
        write_upgrade_sentinel(
            tmp_path,
            chat_id=99,
            old_version="1.0.0",
            new_version="1.1.0",
            transport="feishu",
        )

        assert consume_upgrade_sentinel(tmp_path, transport="telegram") is None
        assert (tmp_path / "upgrade-sentinel.json").exists()

        data = consume_upgrade_sentinel(tmp_path, transport="feishu")
        assert data is not None
        assert data["transport"] == "feishu"


class TestPerformUpgradePipeline:
    """Test upgrade pipeline behavior (verification + retry)."""

    async def test_changes_on_first_attempt(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ) as mock_upgrade,
            patch(
                "controlmesh.infra.updater._wait_for_version_change",
                new=AsyncMock(return_value="2.0.0"),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is True
        assert version == "2.0.0"
        assert "first-pass" in output
        mock_upgrade.assert_called_once_with(target_version=None, force_reinstall=False)

    async def test_retries_with_target_when_unchanged(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(side_effect=[(True, "first-pass"), (True, "retry-pass")]),
            ) as mock_upgrade,
            patch(
                "controlmesh.infra.updater._wait_for_version_change",
                new=AsyncMock(side_effect=["1.0.0", "2.0.0"]),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(
                current_version="1.0.0",
                target_version="2.0.0",
            )

        assert changed is True
        assert version == "2.0.0"
        assert "first-pass" in output
        assert "retry-pass" in output
        assert mock_upgrade.call_count == 2
        assert mock_upgrade.call_args_list[1].kwargs == {
            "target_version": "2.0.0",
            "force_reinstall": True,
        }

    async def test_returns_unchanged_when_no_retry_target(self) -> None:
        with (
            patch(
                "controlmesh.infra.updater._perform_upgrade_impl",
                new=AsyncMock(return_value=(True, "first-pass")),
            ),
            patch(
                "controlmesh.infra.updater._wait_for_version_change",
                new=AsyncMock(return_value="1.0.0"),
            ),
            patch(
                "controlmesh.infra.updater._resolve_retry_target",
                new=AsyncMock(return_value=None),
            ),
        ):
            changed, version, output = await perform_upgrade_pipeline(current_version="1.0.0")

        assert changed is False
        assert version == "1.0.0"
        assert "first-pass" in output


# ---------------------------------------------------------------------------
# UpdateObserver
# ---------------------------------------------------------------------------


class TestUpdateObserver:
    """Test background version check observer."""

    async def test_notifies_on_new_version(self) -> None:
        info = VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="New!")
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=info),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_called_once_with(info)

    async def test_does_not_notify_when_up_to_date(self) -> None:
        info = VersionInfo(current="1.0.0", latest="1.0.0", update_available=False, summary="")
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=info),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_not_called()

    async def test_deduplicates_same_version(self) -> None:
        info = VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="New!")
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=info),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            # Let multiple check cycles run
            await asyncio.sleep(0.15)
            await observer.stop()

        # Should only notify once for the same version
        notify.assert_called_once()

    async def test_handles_check_failure_gracefully(self) -> None:
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch(
                "controlmesh.infra.updater.check_latest_version",
                side_effect=RuntimeError("network"),
            ),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_not_called()

    async def test_handles_none_from_check_latest_version(self) -> None:
        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", return_value=None),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.1)
            await observer.stop()

        notify.assert_not_called()

    async def test_stop_without_start_is_safe(self) -> None:
        observer = UpdateObserver(notify=AsyncMock())
        await observer.stop()  # Should not raise

    async def test_notifies_again_for_newer_version(self) -> None:
        call_count = 0
        versions = [
            VersionInfo(current="1.0.0", latest="2.0.0", update_available=True, summary="v2"),
            VersionInfo(current="1.0.0", latest="3.0.0", update_available=True, summary="v3"),
        ]

        async def mock_check() -> VersionInfo:
            nonlocal call_count
            idx = min(call_count, len(versions) - 1)
            call_count += 1
            return versions[idx]

        notify = AsyncMock()
        observer = UpdateObserver(notify=notify)

        with (
            patch("controlmesh.infra.updater.check_latest_version", side_effect=mock_check),
            patch("controlmesh.infra.updater._INITIAL_DELAY_S", 0),
            patch("controlmesh.infra.updater._CHECK_INTERVAL_S", 0.01),
        ):
            observer.start()
            await asyncio.sleep(0.15)
            await observer.stop()

        assert notify.call_count == 2
