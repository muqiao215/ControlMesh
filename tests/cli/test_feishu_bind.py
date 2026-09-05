"""Existing bot binding must preserve policy and fail before config writes."""

import json
from unittest.mock import AsyncMock

import pytest

from controlmesh.cli_commands import auth, feishu, feishu_bind
from controlmesh.config import AgentConfig
from controlmesh.workspace.paths import resolve_paths


@pytest.fixture
def binding(tmp_path, monkeypatch):
    config = AgentConfig(controlmesh_home=str(tmp_path))
    path = resolve_paths(controlmesh_home=config.controlmesh_home).config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        "transport": "tg",
        "transports": ["tg"],
        "provider": "claude",
        "feishu": {
            "app_id": "cli_old",
            "groups": {},
            "allow_from": ["ou_owner"],
            "group_policy": "disabled",
            "progress_mode": "text",
        },
    }
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(auth, "load_config", lambda: config)
    monkeypatch.setenv("CM_TEST_SECRET", "private-test-secret")
    probe = AsyncMock()
    monkeypatch.setattr(feishu_bind, "verify_bot", probe)
    return path, probe


def test_bind_preserves_settings_and_secret_is_not_printed(binding, capsys):
    path, probe = binding
    feishu.cmd_feishu(["feishu", "bind", "--app-id", "cli_old", "--secret-env", "CM_TEST_SECRET"])
    raw = json.loads(path.read_text())
    assert raw["feishu"]["runtime_mode"] == "native"
    assert raw["feishu"]["allow_from"] == ["ou_owner"]
    assert raw["feishu"]["group_policy"] == "disabled"
    assert raw["feishu"]["progress_mode"] == "text"
    assert raw["transports"] == ["feishu", "tg"]
    assert raw["feishu"]["app_secret"] == "private-test-secret"
    assert path.stat().st_mode & 0o777 == 0o600
    probe.assert_awaited_once_with("cli_old", "private-test-secret")
    assert "private-test-secret" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["credentials", "replace", "pending", "concurrent"])
def test_failures_do_not_overwrite(binding, failure, capsys):
    path, probe = binding
    before = path.read_bytes()
    args = ["--app-id", "cli_old", "--secret-env", "CM_TEST_SECRET"]
    if failure == "credentials":
        probe.side_effect = ValueError("private-test-secret")
    elif failure == "replace":
        args[1] = "cli_new"
    elif failure == "pending":
        (path.parent / "feishu_registration_pending.json").write_text("{}")
    else:

        async def change(*_):
            path.write_bytes(before + b"\n")

        probe.side_effect = change
    with pytest.raises(SystemExit):
        feishu_bind.cmd_bind(args)
    assert path.read_bytes() == before + (b"\n" if failure == "concurrent" else b"")
    assert "private-test-secret" not in capsys.readouterr().out


def test_explicit_replace_and_native_alias(binding):
    path, _ = binding
    feishu.cmd_feishu(
        [
            "feishu",
            "native",
            "bind",
            "--app-id",
            "cli_new",
            "--secret-env",
            "CM_TEST_SECRET",
            "--replace",
        ]
    )
    assert json.loads(path.read_text())["feishu"]["app_id"] == "cli_new"


def test_help_does_not_load_configuration(monkeypatch):
    monkeypatch.setattr(auth, "load_config", lambda: pytest.fail("help loaded config"))
    with pytest.raises(SystemExit) as exc:
        feishu.cmd_feishu(["feishu", "bind", "--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize(
    ("token_data", "bot_data", "accepted"),
    [
        (
            {"code": 0, "tenant_access_token": "token"},
            {"code": 0, "bot": {"open_id": "ou_bot"}},
            True,
        ),
        ({"code": 1}, {}, False),
        ({"code": 0}, {}, False),
        ({"code": 0, "tenant_access_token": "token"}, {"code": 0, "bot": {}}, False),
        ({"code": 0, "tenant_access_token": "token"}, {"code": 1}, False),
    ],
)
async def test_bot_verification_contract(monkeypatch, token_data, bot_data, accepted):
    from unittest.mock import MagicMock

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    for method, payload in [(session.post, token_data), (session.get, bot_data)]:
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=payload)
        method.return_value.__aenter__ = AsyncMock(return_value=response)
        method.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(feishu_bind.aiohttp, "ClientSession", lambda **_: session)
    if accepted:
        await feishu_bind.verify_bot("cli_test", "secret")
        assert session.get.call_args.args[0].endswith("/bot/v3/info")
        assert session.get.call_args.kwargs["allow_redirects"] is False
    else:
        with pytest.raises(
            ValueError,
            match=r"credentials_rejected|token_missing|bot_identity_missing|bot_unavailable",
        ):
            await feishu_bind.verify_bot("cli_test", "secret")
