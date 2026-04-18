from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path

from .agent_runtime import AgentTurnRequest, CodexCliRunner, EchoRunner
from .app_registration import AppRegistrationClient, AppRegistrationPollResult
from .cardkit import build_single_card_run
from .claude_adapter import (
    build_claude_device_flow_payload,
    build_claude_permission_payload,
)
from .client import FeishuApiError, FeishuAuthClient
from .device_flow import DeviceFlowClient, DeviceFlowError
from .message_context import parse_feishu_message_context
from .models import DeviceAuthorization
from .native_contract import (
    NativeCardAction,
    bind_auth_continuation_to_native,
    build_retry_artifact_from_request,
    resolve_card_action_to_retry,
)
from .orchestration import (
    AuthRequirement,
    FilePendingFlowRegistry,
    build_synthetic_retry_artifact,
    load_auth_continuation,
    plan_scope_authorization,
    route_auth_requirement,
    verify_access_token_identity,
)
from .owner_policy import OwnerPolicyMode, check_owner_policy
from .probe import register_ai_agent
from .runtime_cards import (
    CardAction,
    ContinuationState,
    FileContinuationStore,
    build_device_flow_card,
    build_permission_missing_card,
    new_operation_id,
    process_card_action,
)
from .scopes import (
    batch_scopes,
    filter_sensitive_scopes,
    missing_core_scopes,
    summarize_scope_batches,
)
from .token_store import FileTokenStore, StoredUserToken


def format_setup_guide(brand: str = "feishu") -> str:
    platform = "open.larksuite.com" if brand == "lark" else "open.feishu.cn"
    return "\n".join(
        [
            "Feishu / Lark app setup guide",
            "",
            "This kit supports the official scan-to-create app registration flow.",
            "It still does not bypass Open Platform approval, review, or publishing policy.",
            "",
            "Zero-start checklist:",
            "1. Try `feishu-auth-kit register scan-create` for official QR onboarding.",
            f"2. If scan-create is unavailable, open {platform} and create an app manually.",
            "3. Copy App ID and App Secret from the credentials page.",
            "4. Enable core permissions:",
            "   - application:application:self_manage",
            "   - offline_access",
            "5. Add the user or tenant scopes your downstream tool actually needs.",
            "6. Publish or release the app according to Feishu/Lark policy.",
            "7. Run `feishu-auth-kit doctor --app-id ... --app-secret ...`.",
            "",
            "This repository guides setup and automates validation and OAuth.",
        ]
    )


def _split_csv(items: Iterable[str] | None) -> list[str]:
    scopes: list[str] = []
    for item in items or []:
        scopes.extend(part.strip() for part in item.split(","))
    return [scope for scope in scopes if scope]


def _credentials_from_args(args: argparse.Namespace) -> tuple[str | None, str | None]:
    app_id = args.app_id or os.getenv("FEISHU_APP_ID") or os.getenv("LARK_APP_ID")
    app_secret = (
        args.app_secret or os.getenv("FEISHU_APP_SECRET") or os.getenv("LARK_APP_SECRET")
    )
    return app_id, app_secret


def _default_brand() -> str:
    return os.getenv("FEISHU_BRAND") or os.getenv("LARK_BRAND") or "feishu"


def _require_client(args: argparse.Namespace) -> FeishuAuthClient:
    app_id, app_secret = _credentials_from_args(args)
    if not app_id or not app_secret:
        raise SystemExit("Missing app credentials. Pass --app-id/--app-secret or set env vars.")
    return FeishuAuthClient(app_id, app_secret, brand=args.brand)


def _resolve_login_scopes(args: argparse.Namespace, client: FeishuAuthClient) -> list[str]:
    explicit = _split_csv(args.scope)
    if explicit:
        return explicit
    if getattr(args, "all_app_user_scopes", False):
        return client.get_granted_scopes(token_type="user")
    return client.get_granted_scopes(token_type="user")


def _print_scope_block(title: str, scopes: list[str]) -> None:
    print(f"{title}: {len(scopes)}")
    for scope in scopes:
        print(f"  - {scope}")


def _json_dump(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _json_line(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _load_json_file(path_value: str) -> dict:
    return json.loads(Path(path_value).expanduser().read_text(encoding="utf-8"))


def _token_store_from_args(args: argparse.Namespace) -> FileTokenStore:
    return FileTokenStore(getattr(args, "token_store_path", None))


def _continuation_store_from_args(args: argparse.Namespace) -> FileContinuationStore:
    return FileContinuationStore(getattr(args, "continuation_store_path", None))


def _pending_flow_store_from_args(args: argparse.Namespace) -> FilePendingFlowRegistry:
    return FilePendingFlowRegistry(getattr(args, "pending_flow_store_path", None))


def _registration_client_from_args(args: argparse.Namespace) -> AppRegistrationClient:
    return AppRegistrationClient(brand=args.brand)


def _print_registration_begin(result: object) -> None:
    payload = {
        "status": "authorization_required",
        "device_code": result.device_code,
        "user_code": result.user_code,
        "qr_url": result.qr_url,
        "verification_uri": result.verification_uri,
        "verification_uri_complete": result.verification_uri_complete,
        "interval": result.interval,
        "expires_in": result.expires_in,
    }
    _json_dump(payload)


def _print_registration_poll_result(outcome: AppRegistrationPollResult) -> int:
    if outcome.status == "success" and outcome.result is not None:
        _json_dump(
            {
                "status": outcome.status,
                "app_id": outcome.result.app_id,
                "app_secret": outcome.result.app_secret,
                "domain": outcome.result.domain,
                "open_id": outcome.result.open_id,
            }
        )
        return 0
    payload: dict[str, object] = {"status": outcome.status}
    if outcome.message:
        payload["message"] = outcome.message
    _json_dump(payload)
    return 1


def _write_registration_env_file(path_value: str, outcome: AppRegistrationPollResult) -> None:
    if outcome.status != "success" or outcome.result is None:
        return
    path = Path(path_value).expanduser()
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"FEISHU_APP_ID={outcome.result.app_id}",
        f"FEISHU_APP_SECRET={outcome.result.app_secret}",
        f"FEISHU_BRAND={outcome.result.domain}",
    ]
    if outcome.result.open_id:
        lines.append(f"FEISHU_OWNER_OPEN_ID={outcome.result.open_id}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_setup(args: argparse.Namespace) -> int:
    print(format_setup_guide(args.brand))
    return 0


def cmd_register_init(args: argparse.Namespace) -> int:
    result = _registration_client_from_args(args).init()
    if args.json:
        _json_dump(
            {
                "status": "supported",
                "nonce": result.nonce,
                "supported_auth_methods": result.supported_auth_methods,
            }
        )
    else:
        print("Official app registration is supported in this environment.")
        print(f"Supported auth methods: {', '.join(result.supported_auth_methods)}")
    return 0


def cmd_register_begin(args: argparse.Namespace) -> int:
    result = _registration_client_from_args(args).begin()
    if args.json:
        _print_registration_begin(result)
    else:
        print("Scan-to-create authorization")
        print(f"QR URL: {result.qr_url}")
        print(f"Verification URL: {result.verification_uri_complete}")
        print(f"User code: {result.user_code}")
        print(f"Device code: {result.device_code}")
        print(f"Poll interval: {result.interval}s")
        print(f"Expires in: {result.expires_in}s")
    return 0


def cmd_register_poll(args: argparse.Namespace) -> int:
    outcome = _registration_client_from_args(args).poll(
        args.device_code,
        interval=args.interval,
        expires_in=args.expires_in,
        tp=args.tp,
        poll_timeout=args.poll_timeout,
    )
    if outcome.status == "success" and outcome.result is not None and args.write_env_file:
        _write_registration_env_file(args.write_env_file, outcome)
    if args.json:
        return _print_registration_poll_result(outcome)
    if outcome.status == "success" and outcome.result is not None:
        print("Scan-to-create completed.")
        print(f"App ID: {outcome.result.app_id}")
        print(f"App Secret: {outcome.result.app_secret}")
        print(f"Domain: {outcome.result.domain}")
        if outcome.result.open_id:
            print(f"Owner open_id: {outcome.result.open_id}")
        if args.write_env_file:
            print(f"Wrote env file: {Path(args.write_env_file).expanduser()}")
        return 0
    print(f"Registration status: {outcome.status}")
    if outcome.message:
        print(f"Message: {outcome.message}")
    return 1


def cmd_register_scan_create(args: argparse.Namespace) -> int:
    client = _registration_client_from_args(args)
    client.init()
    begin = client.begin()
    if args.no_poll:
        if args.json:
            _print_registration_begin(begin)
        else:
            print("Scan-to-create authorization")
            print(f"QR URL: {begin.qr_url}")
            print(f"User code: {begin.user_code}")
            print(f"Device code: {begin.device_code}")
        return 0
    outcome = client.poll(
        begin.device_code,
        interval=begin.interval,
        expires_in=begin.expires_in,
        tp=args.tp,
        poll_timeout=args.poll_timeout,
    )
    if outcome.status == "success" and outcome.result is not None and args.write_env_file:
        _write_registration_env_file(args.write_env_file, outcome)
    if args.json:
        return _print_registration_poll_result(outcome)
    if outcome.status == "success" and outcome.result is not None:
        print("Scan-to-create completed.")
        print(f"App ID: {outcome.result.app_id}")
        print(f"App Secret: {outcome.result.app_secret}")
        print(f"Domain: {outcome.result.domain}")
        if outcome.result.open_id:
            print(f"Owner open_id: {outcome.result.open_id}")
        if args.write_env_file:
            print(f"Wrote env file: {Path(args.write_env_file).expanduser()}")
        return 0
    print(f"Registration status: {outcome.status}")
    if outcome.message:
        print(f"Message: {outcome.message}")
    return 1


def cmd_register_probe(args: argparse.Namespace) -> int:
    client = _require_client(args)
    result = register_ai_agent(client)
    payload = {
        "ok": result.ok,
        "app_id": result.app_id,
        "bot_name": result.bot_name,
        "bot_open_id": result.bot_open_id,
        "error": result.error,
    }
    if args.json:
        _json_dump(payload)
    else:
        print(f"OK: {'yes' if result.ok else 'no'}")
        print(f"App ID: {result.app_id}")
        if result.bot_name:
            print(f"Bot name: {result.bot_name}")
        if result.bot_open_id:
            print(f"Bot open_id: {result.bot_open_id}")
        if result.error:
            print(f"Error: {result.error}")
    return 0 if result.ok else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    client = _require_client(args)
    exit_code = 0
    print("Doctor report")
    print(f"Brand: {args.brand}")
    print(f"App ID: {client.app_id}")
    try:
        tenant_token = client.get_tenant_access_token()
        print("Tenant token: OK")
        print(f"Tenant token TTL: {tenant_token.expire or 'unknown'}")
    except FeishuApiError as exc:
        print(f"Tenant token: FAILED ({exc})")
        return 1

    try:
        app_info = client.get_app_info(args.target_app_id)
    except FeishuApiError as exc:
        print(f"App info: FAILED ({exc})")
        permission_url = client.build_permission_url(
            client.app_id,
            scopes=["application:application:self_manage"],
        )
        print(f"Grant application self-management: {permission_url}")
        return 1

    print(f"App info: OK ({app_info.app_id})")
    if app_info.name:
        print(f"App name: {app_info.name}")
    if app_info.effective_owner_open_id:
        print(f"App owner open_id: {app_info.effective_owner_open_id}")
    tenant_scopes = client.get_granted_scopes(token_type="tenant", app_info=app_info)
    user_scopes = client.get_granted_scopes(token_type="user", app_info=app_info)
    all_scopes = client.get_granted_scopes(app_info=app_info)
    _print_scope_block("Tenant scopes", tenant_scopes)
    _print_scope_block("User scopes", user_scopes)

    missing = missing_core_scopes(all_scopes)
    if missing:
        exit_code = 1
        print("Missing core permissions:")
        for scope in missing:
            token_type = "user" if scope == "offline_access" else "tenant"
            url = client.build_permission_url(
                app_info.app_id or client.app_id,
                scopes=[scope],
                token_type=token_type,
            )
            print(f"  - {scope}")
            print(f"    {url}")
    else:
        print("Missing core permissions: none")
    return exit_code


def cmd_scopes(args: argparse.Namespace) -> int:
    client = _require_client(args)
    scopes = client.get_granted_scopes(token_type=args.token_type or None)
    print(f"Granted scopes: {len(scopes)}")
    for scope in scopes:
        print(scope)
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    client = _require_client(args)
    scopes = _resolve_login_scopes(args, client)
    if not scopes:
        print("No scopes available for device flow.")
        return 1
    flow = DeviceFlowClient(client.app_id, client.app_secret, brand=args.brand)
    auth = flow.request_authorization(scopes)
    print(f"Verification URL: {auth.verification_uri}")
    print(f"Verification URL (complete): {auth.verification_uri_complete}")
    print(f"User code: {auth.user_code}")
    print(f"Expires in: {auth.expires_in}s")
    print(f"Poll interval: {auth.interval}s")
    print(f"Requested scopes: {' '.join(scopes)}")
    if args.no_poll:
        return 0
    try:
        token = flow.poll_for_token(
            auth.device_code,
            interval=auth.interval,
            expires_in=auth.expires_in,
        )
    except DeviceFlowError as exc:
        print(f"Device flow polling failed: {exc}")
        return 1
    print("Device flow completed.")
    print(f"Access token acquired: {'yes' if token.access_token else 'no'}")
    print(f"Granted scope: {token.scope or '(not returned)'}")
    save_user_open_id = getattr(args, "save_user_open_id", None)
    if save_user_open_id:
        stored = _token_store_from_args(args).save_device_token(
            client.app_id,
            save_user_open_id,
            token,
        )
        print(f"Stored token for {stored.user_open_id} at {_token_store_from_args(args).path}")
    return 0


def cmd_batch_auth(args: argparse.Namespace) -> int:
    client = _require_client(args)
    user_scopes = client.get_granted_scopes(token_type="user")
    safe_scopes = filter_sensitive_scopes(user_scopes)
    batches = batch_scopes(safe_scopes, batch_size=args.batch_size)
    if not batches:
        print("No user scopes available for batch authorization.")
        return 1
    for line in summarize_scope_batches(batches):
        print(line)

    flow = DeviceFlowClient(client.app_id, client.app_secret, brand=args.brand)
    for index, batch in enumerate(batches, start=1):
        print(f"Starting batch {index}/{len(batches)}")
        print("Scopes:")
        for scope in batch:
            print(f"  - {scope}")
        auth = flow.request_authorization(batch)
        print(f"Open: {auth.verification_uri_complete}")
        print(f"User code: {auth.user_code}")
        if args.no_poll:
            print("Stopping after link generation because --no-poll was used.")
            return 0
        try:
            token = flow.poll_for_token(
                auth.device_code,
                interval=auth.interval,
                expires_in=auth.expires_in,
            )
        except DeviceFlowError as exc:
            print(f"Batch {index} failed: {exc}")
            return 1
        if args.save_user_open_id:
            _token_store_from_args(args).save_device_token(
                client.app_id,
                args.save_user_open_id,
                token,
            )
    return 0


def cmd_tokens_status(args: argparse.Namespace) -> int:
    status = _token_store_from_args(args).status(args.app_id, args.user_open_id)
    if args.json:
        _json_dump(
            {
                "app_id": status.app_id,
                "user_open_id": status.user_open_id,
                "exists": status.exists,
                "scope": status.scope,
                "expires_at": status.expires_at,
                "refresh_expires_at": status.refresh_expires_at,
                "storage_path": str(status.storage_path),
            }
        )
    else:
        print(f"Exists: {'yes' if status.exists else 'no'}")
        print(f"Storage path: {status.storage_path}")
        if status.exists:
            print(f"Scope: {status.scope or '(unknown)'}")
            print(f"Expires at: {status.expires_at or 'unknown'}")
    return 0


def cmd_tokens_show(args: argparse.Namespace) -> int:
    token = _token_store_from_args(args).load(args.app_id, args.user_open_id)
    if not token:
        print("Token not found.")
        return 1
    _json_dump(
        {
            "app_id": token.app_id,
            "user_open_id": token.user_open_id,
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "expires_at": token.expires_at,
            "refresh_expires_at": token.refresh_expires_at,
            "scope": token.scope,
        }
    )
    return 0


def cmd_tokens_save(args: argparse.Namespace) -> int:
    token = StoredUserToken(
        app_id=args.app_id,
        user_open_id=args.user_open_id,
        access_token=args.access_token,
        refresh_token=args.refresh_token,
        expires_at=args.expires_at,
        refresh_expires_at=args.refresh_expires_at,
        scope=args.scope,
    )
    store = _token_store_from_args(args)
    store.save(token)
    print(f"Saved token to {store.path}")
    return 0


def cmd_tokens_remove(args: argparse.Namespace) -> int:
    removed = _token_store_from_args(args).remove(args.app_id, args.user_open_id)
    print("Removed." if removed else "Token not found.")
    return 0 if removed else 1


def cmd_owner_check(args: argparse.Namespace) -> int:
    client = _require_client(args)
    mode = OwnerPolicyMode(args.mode)
    result = check_owner_policy(
        client,
        current_user_open_id=args.current_user_open_id,
        mode=mode,
        app_id=args.target_app_id,
    )
    if args.json:
        _json_dump(
            {
                "allowed": result.allowed,
                "mode": result.mode.value,
                "owner_open_id": result.owner_open_id,
                "current_user_open_id": result.current_user_open_id,
                "reason": result.reason,
                "app_id": result.app_info.app_id,
            }
        )
    else:
        print(f"Allowed: {'yes' if result.allowed else 'no'}")
        print(f"Mode: {result.mode.value}")
        print(f"Owner open_id: {result.owner_open_id or '(unknown)'}")
        print(f"Reason: {result.reason}")
    return 0 if result.allowed else 1


def _save_card_state(
    args: argparse.Namespace,
    *,
    operation_id: str,
    kind: str,
    payload: dict[str, object],
) -> None:
    _continuation_store_from_args(args).save(
        ContinuationState(
            operation_id=operation_id,
            app_id=args.app_id,
            kind=kind,
            status="waiting",
            payload=payload,
        )
    )


def cmd_runtime_permission_card(args: argparse.Namespace) -> int:
    operation_id = args.operation_id or new_operation_id()
    missing_scopes = _split_csv(args.scope)
    card = build_permission_missing_card(
        app_id=args.app_id,
        operation_id=operation_id,
        missing_scopes=missing_scopes,
        permission_url=args.permission_url,
        user_open_id=args.user_open_id,
    )
    _save_card_state(
        args,
        operation_id=operation_id,
        kind="permission_missing",
        payload={
            "missing_scopes": missing_scopes,
            "permission_url": args.permission_url,
            "user_open_id": args.user_open_id,
        },
    )
    _json_dump(card.to_dict())
    return 0


def cmd_runtime_device_card(args: argparse.Namespace) -> int:
    operation_id = args.operation_id or new_operation_id()
    authorization = DeviceAuthorization(
        device_code=args.device_code,
        user_code=args.user_code,
        verification_uri=args.verification_uri,
        verification_uri_complete=args.verification_uri_complete or args.verification_uri,
        expires_in=args.expires_in,
        interval=args.interval,
    )
    card = build_device_flow_card(
        app_id=args.app_id,
        operation_id=operation_id,
        authorization=authorization,
    )
    _save_card_state(
        args,
        operation_id=operation_id,
        kind="device_flow_authorization",
        payload=card.to_dict()["fields"],
    )
    _json_dump(card.to_dict())
    return 0


def cmd_runtime_continue(args: argparse.Namespace) -> int:
    result = process_card_action(
        CardAction(
            action=args.action,
            payload={
                "operation_id": args.operation_id,
                "actor_open_id": args.actor_open_id,
            },
        ),
        _continuation_store_from_args(args),
    )
    _json_dump(
        {
            "operation_id": result.operation_id,
            "app_id": result.app_id,
            "kind": result.kind,
            "status": result.status,
            "payload": result.payload,
        }
    )
    return 0


def cmd_claude_permission_card(args: argparse.Namespace) -> int:
    operation_id = args.operation_id or new_operation_id()
    missing_scopes = _split_csv(args.scope)
    _save_card_state(
        args,
        operation_id=operation_id,
        kind="permission_missing",
        payload={
            "missing_scopes": missing_scopes,
            "permission_url": args.permission_url,
            "user_open_id": args.user_open_id,
        },
    )
    payload = build_claude_permission_payload(
        app_id=args.app_id,
        operation_id=operation_id,
        missing_scopes=missing_scopes,
        permission_url=args.permission_url,
        user_open_id=args.user_open_id,
    )
    _json_dump(payload)
    return 0


def cmd_claude_device_card(args: argparse.Namespace) -> int:
    operation_id = args.operation_id or new_operation_id()
    authorization = DeviceAuthorization(
        device_code=args.device_code,
        user_code=args.user_code,
        verification_uri=args.verification_uri,
        verification_uri_complete=args.verification_uri_complete or args.verification_uri,
        expires_in=args.expires_in,
        interval=args.interval,
    )
    _save_card_state(
        args,
        operation_id=operation_id,
        kind="device_flow_authorization",
        payload={
            "device_code": authorization.device_code,
            "user_code": authorization.user_code,
            "verification_uri": authorization.verification_uri,
            "verification_uri_complete": authorization.verification_uri_complete,
            "expires_in": authorization.expires_in,
            "interval": authorization.interval,
        },
    )
    payload = build_claude_device_flow_payload(
        app_id=args.app_id,
        operation_id=operation_id,
        authorization=authorization,
    )
    _json_dump(payload)
    return 0


def cmd_orchestration_plan(args: argparse.Namespace) -> int:
    requested_scopes = _split_csv(args.requested_scope)
    plan = plan_scope_authorization(
        requested_scopes=requested_scopes,
        app_granted_scopes=_split_csv(args.app_scope),
        user_granted_scopes=_split_csv(args.user_scope),
        batch_size=args.batch_size,
        filter_sensitive=not args.keep_sensitive,
    )
    _json_dump(
        {
            "requested_scopes": plan.requested_scopes,
            "app_granted_scopes": plan.app_granted_scopes,
            "user_granted_scopes": plan.user_granted_scopes,
            "already_granted_scopes": plan.already_granted_scopes,
            "missing_user_scopes": plan.missing_user_scopes,
            "unavailable_scopes": plan.unavailable_scopes,
            "batches": plan.batches,
        }
    )
    return 0


def cmd_orchestration_route(args: argparse.Namespace) -> int:
    authorization = None
    if args.error_kind != "app_scope_missing":
        authorization = DeviceAuthorization(
            device_code=args.device_code,
            user_code=args.user_code,
            verification_uri=args.verification_uri,
            verification_uri_complete=args.verification_uri_complete or args.verification_uri,
            expires_in=args.expires_in,
            interval=args.interval,
        )
    result = route_auth_requirement(
        app_id=args.app_id,
        requirement=AuthRequirement(
            error_kind=args.error_kind,
            required_scopes=_split_csv(args.required_scope),
            token_type=args.token_type,
            scope_need_type=args.scope_need_type,
            user_open_id=args.user_open_id,
            flow_key=args.flow_key,
            operation_id=args.operation_id,
            metadata={"source": args.source} if args.source else {},
        ),
        pending_flows=_pending_flow_store_from_args(args),
        continuation_store=_continuation_store_from_args(args),
        permission_url=args.permission_url,
        authorization=authorization,
    )
    _json_dump(
        {
            "decision": result.decision,
            "reused_existing_flow": result.reused_existing_flow,
            "flow": {
                "flow_key": result.flow.flow_key,
                "operation_id": result.flow.operation_id,
                "required_scopes": result.flow.required_scopes,
                "token_type": result.flow.token_type,
                "scope_need_type": result.flow.scope_need_type,
            },
            "continuation": result.continuation.to_state().payload,
            "card": result.card.to_dict() if result.card else None,
        }
    )
    return 0


def cmd_orchestration_retry(args: argparse.Namespace) -> int:
    continuation = load_auth_continuation(
        _continuation_store_from_args(args),
        args.operation_id,
    )
    if continuation is None:
        print("Continuation not found.")
        return 1
    artifact = build_synthetic_retry_artifact(
        operation_id=continuation.operation_id,
        app_id=continuation.app_id,
        user_open_id=continuation.user_open_id,
        text=args.text,
        reason=args.reason,
        metadata={"flow_key": continuation.flow_key, **continuation.metadata},
    )
    _json_dump(artifact.to_dict())
    return 0


def cmd_orchestration_verify_identity(args: argparse.Namespace) -> int:
    result = verify_access_token_identity(
        access_token=args.access_token,
        expected_open_id=args.expected_open_id,
        brand=args.brand,
    )
    _json_dump(
        {
            "valid": result.valid,
            "expected_open_id": result.expected_open_id,
            "actual_open_id": result.actual_open_id,
        }
    )
    return 0 if result.valid else 1


def cmd_agent_parse_inbound(args: argparse.Namespace) -> int:
    context = parse_feishu_message_context(_load_json_file(args.event_file))
    _json_dump(context.to_dict())
    return 0


def cmd_agent_run(args: argparse.Namespace) -> int:
    context = parse_feishu_message_context(_load_json_file(args.event_file))
    request = AgentTurnRequest.from_message_context(
        context,
        system_prompt=args.system_prompt,
        session_id=args.session_id,
    )
    if args.runner == "codex":
        runner = CodexCliRunner(
            codex_bin=args.codex_bin,
            model=args.model,
            cwd=args.codex_cd,
            extra_args=args.codex_arg,
            timeout=args.timeout,
        )
    else:
        runner = EchoRunner(prefix=args.echo_prefix)
    result = runner.run(request)
    card = build_single_card_run(context, result)
    if args.emit_events:
        for index, event in enumerate(result.events, start=1):
            _json_line(
                {
                    "schema": "feishu-auth-kit.agent-event.v1",
                    "index": index,
                    "runner": result.runner,
                    **event.to_dict(),
                }
            )
        _json_line(
            {
                "schema": "feishu-auth-kit.agent-run-summary.v1",
                "result": result.to_dict(),
                "card": card.to_dict(),
            }
        )
        return 0 if result.status == "completed" else 1
    _json_dump(
        {
            "schema": "feishu-auth-kit.agent-run.v1",
            "context": context.to_dict(),
            "request": request.to_dict(),
            "result": result.to_dict(),
            "card": card.to_dict(),
        }
    )
    return 0 if result.status == "completed" else 1


def cmd_agent_bind_continuation(args: argparse.Namespace) -> int:
    continuation = bind_auth_continuation_to_native(
        _continuation_store_from_args(args),
        operation_id=args.operation_id,
        retry_text=args.text,
        metadata={"source": args.source} if args.source else {},
    )
    _json_dump(continuation.to_dict())
    return 0


def cmd_agent_action_to_retry(args: argparse.Namespace) -> int:
    resolved = resolve_card_action_to_retry(
        NativeCardAction(
            operation_id=args.operation_id,
            action=args.action,
            actor_open_id=args.actor_open_id,
            message_id=args.message_id,
            payload=_load_json_file(args.payload_file) if args.payload_file else {},
        ),
        _continuation_store_from_args(args),
    )
    artifact = build_retry_artifact_from_request(resolved.retry_request)
    _json_dump(
        {
            **resolved.to_dict(),
            "retry_artifact": artifact.to_dict(),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu-auth-kit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--brand", default=_default_brand(), choices=["feishu", "lark"])
    common.add_argument("--app-id")
    common.add_argument("--app-secret")

    setup_parser = subparsers.add_parser("setup", help="Print zero-start app setup guidance.")
    setup_parser.add_argument("--brand", default=_default_brand(), choices=["feishu", "lark"])
    setup_parser.set_defaults(func=cmd_setup)

    register_parser = subparsers.add_parser(
        "register",
        help="Use the official Feishu/Lark scan-to-create app registration flow.",
    )
    register_subparsers = register_parser.add_subparsers(dest="register_command", required=True)
    register_common = argparse.ArgumentParser(add_help=False)
    register_common.add_argument("--brand", default=_default_brand(), choices=["feishu", "lark"])

    register_init_parser = register_subparsers.add_parser(
        "init",
        parents=[register_common],
        help="Check whether official app registration supports client_secret auth.",
    )
    register_init_parser.add_argument("--json", action="store_true")
    register_init_parser.set_defaults(func=cmd_register_init)

    register_begin_parser = register_subparsers.add_parser(
        "begin",
        parents=[register_common],
        help="Begin official scan-to-create app registration and print QR/link details.",
    )
    register_begin_parser.add_argument("--json", action="store_true")
    register_begin_parser.set_defaults(func=cmd_register_begin)

    register_poll_parser = register_subparsers.add_parser(
        "poll",
        parents=[register_common],
        help="Poll an in-flight official app registration device code.",
    )
    register_poll_parser.add_argument("--device-code", required=True)
    register_poll_parser.add_argument("--interval", type=int, default=5)
    register_poll_parser.add_argument("--expires-in", type=int, default=600)
    register_poll_parser.add_argument("--poll-timeout", type=int)
    register_poll_parser.add_argument("--tp", default="ob_app")
    register_poll_parser.add_argument("--write-env-file")
    register_poll_parser.add_argument("--json", action="store_true")
    register_poll_parser.set_defaults(func=cmd_register_poll)

    register_scan_parser = register_subparsers.add_parser(
        "scan-create",
        parents=[register_common],
        help="Run init + begin and optionally poll until scan-to-create completes.",
    )
    register_scan_parser.add_argument("--no-poll", action="store_true")
    register_scan_parser.add_argument("--poll-timeout", type=int)
    register_scan_parser.add_argument("--tp", default="ob_app")
    register_scan_parser.add_argument("--write-env-file")
    register_scan_parser.add_argument("--json", action="store_true")
    register_scan_parser.set_defaults(func=cmd_register_scan_create)

    register_probe_parser = register_subparsers.add_parser(
        "probe",
        parents=[common],
        help="Validate credentials and register the app as an AI agent via ping.",
    )
    register_probe_parser.add_argument("--json", action="store_true")
    register_probe_parser.set_defaults(func=cmd_register_probe)

    doctor_parser = subparsers.add_parser(
        "doctor",
        parents=[common],
        help="Validate app credentials, token, app info, scopes, and core permissions.",
    )
    doctor_parser.add_argument("--target-app-id", default="me")
    doctor_parser.set_defaults(func=cmd_doctor)

    scopes_parser = subparsers.add_parser(
        "scopes",
        parents=[common],
        help="List granted app scopes.",
    )
    scopes_parser.add_argument("--token-type", choices=["user", "tenant"])
    scopes_parser.set_defaults(func=cmd_scopes)

    login_help = "Run OAuth device flow for explicit scopes or all app user scopes."
    auth_url_parser = subparsers.add_parser("auth-url", parents=[common], help=login_help)
    auth_url_parser.add_argument("--scope", action="append", default=[])
    auth_url_parser.add_argument("--all-app-user-scopes", action="store_true")
    auth_url_parser.add_argument("--no-poll", action="store_true")
    auth_url_parser.set_defaults(func=cmd_login)

    login_parser = subparsers.add_parser("login", parents=[common], help=login_help)
    login_parser.add_argument("--scope", action="append", default=[])
    login_parser.add_argument("--all-app-user-scopes", action="store_true")
    login_parser.add_argument("--no-poll", action="store_true")
    login_parser.add_argument("--save-user-open-id")
    login_parser.add_argument("--token-store-path")
    login_parser.set_defaults(func=cmd_login)

    batch_parser = subparsers.add_parser(
        "batch-auth",
        parents=[common],
        help="Split safe app user scopes into batches and authorize one batch at a time.",
    )
    batch_parser.add_argument("--batch-size", type=int, default=100)
    batch_parser.add_argument("--no-poll", action="store_true")
    batch_parser.add_argument("--save-user-open-id")
    batch_parser.add_argument("--token-store-path")
    batch_parser.set_defaults(func=cmd_batch_auth)

    tokens_parser = subparsers.add_parser(
        "tokens",
        help="Persist, inspect, and remove user tokens from a file-backed store.",
    )
    tokens_subparsers = tokens_parser.add_subparsers(dest="tokens_command", required=True)
    token_common = argparse.ArgumentParser(add_help=False)
    token_common.add_argument("--app-id", required=True)
    token_common.add_argument("--user-open-id", required=True)
    token_common.add_argument("--token-store-path")

    tokens_status_parser = tokens_subparsers.add_parser(
        "status",
        parents=[token_common],
        help="Show token presence and metadata.",
    )
    tokens_status_parser.add_argument("--json", action="store_true")
    tokens_status_parser.set_defaults(func=cmd_tokens_status)

    tokens_show_parser = tokens_subparsers.add_parser(
        "show",
        parents=[token_common],
        help="Load and print a stored token.",
    )
    tokens_show_parser.set_defaults(func=cmd_tokens_show)

    tokens_save_parser = tokens_subparsers.add_parser(
        "save",
        parents=[token_common],
        help="Store a token explicitly.",
    )
    tokens_save_parser.add_argument("--access-token", required=True)
    tokens_save_parser.add_argument("--refresh-token")
    tokens_save_parser.add_argument("--expires-at", type=int)
    tokens_save_parser.add_argument("--refresh-expires-at", type=int)
    tokens_save_parser.add_argument("--scope")
    tokens_save_parser.set_defaults(func=cmd_tokens_save)

    tokens_remove_parser = tokens_subparsers.add_parser(
        "remove",
        parents=[token_common],
        help="Delete a stored token.",
    )
    tokens_remove_parser.set_defaults(func=cmd_tokens_remove)

    owner_parser = subparsers.add_parser(
        "owner-check",
        parents=[common],
        help="Enforce app owner policy against current user open_id.",
    )
    owner_parser.add_argument("--target-app-id", default="me")
    owner_parser.add_argument("--current-user-open-id", required=True)
    owner_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in OwnerPolicyMode],
        default=OwnerPolicyMode.STRICT_OWNER.value,
    )
    owner_parser.add_argument("--json", action="store_true")
    owner_parser.set_defaults(func=cmd_owner_check)

    runtime_parser = subparsers.add_parser(
        "runtime",
        help="Build generic interactive card payloads and process continuation actions.",
    )
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_common = argparse.ArgumentParser(add_help=False)
    runtime_common.add_argument("--app-id", required=True)
    runtime_common.add_argument("--operation-id")
    runtime_common.add_argument("--continuation-store-path")

    runtime_permission_parser = runtime_subparsers.add_parser(
        "permission-card",
        parents=[runtime_common],
        help="Emit a generic permission-missing card JSON payload.",
    )
    runtime_permission_parser.add_argument("--scope", action="append", default=[], required=True)
    runtime_permission_parser.add_argument("--permission-url", required=True)
    runtime_permission_parser.add_argument("--user-open-id")
    runtime_permission_parser.set_defaults(func=cmd_runtime_permission_card)

    runtime_device_parser = runtime_subparsers.add_parser(
        "device-card",
        parents=[runtime_common],
        help="Emit a generic device-flow authorization card JSON payload.",
    )
    runtime_device_parser.add_argument("--device-code", required=True)
    runtime_device_parser.add_argument("--user-code", required=True)
    runtime_device_parser.add_argument("--verification-uri", required=True)
    runtime_device_parser.add_argument("--verification-uri-complete")
    runtime_device_parser.add_argument("--expires-in", type=int, required=True)
    runtime_device_parser.add_argument("--interval", type=int, default=5)
    runtime_device_parser.set_defaults(func=cmd_runtime_device_card)

    runtime_continue_parser = runtime_subparsers.add_parser(
        "continue",
        help="Process a user-confirmed continuation action.",
    )
    runtime_continue_parser.add_argument("--operation-id", required=True)
    runtime_continue_parser.add_argument("--action", required=True)
    runtime_continue_parser.add_argument("--actor-open-id")
    runtime_continue_parser.add_argument("--continuation-store-path")
    runtime_continue_parser.set_defaults(func=cmd_runtime_continue)

    claude_parser = subparsers.add_parser(
        "claude",
        help="Emit Claude-facing structured JSON payloads based on generic card abstractions.",
    )
    claude_subparsers = claude_parser.add_subparsers(dest="claude_command", required=True)
    claude_common = argparse.ArgumentParser(add_help=False)
    claude_common.add_argument("--app-id", required=True)
    claude_common.add_argument("--operation-id")
    claude_common.add_argument("--continuation-store-path")

    claude_permission_parser = claude_subparsers.add_parser(
        "permission-card",
        parents=[claude_common],
        help="Emit a Claude-facing permission card wrapper.",
    )
    claude_permission_parser.add_argument("--scope", action="append", default=[], required=True)
    claude_permission_parser.add_argument("--permission-url", required=True)
    claude_permission_parser.add_argument("--user-open-id")
    claude_permission_parser.set_defaults(func=cmd_claude_permission_card)

    claude_device_parser = claude_subparsers.add_parser(
        "device-card",
        parents=[claude_common],
        help="Emit a Claude-facing device-flow card wrapper.",
    )
    claude_device_parser.add_argument("--device-code", required=True)
    claude_device_parser.add_argument("--user-code", required=True)
    claude_device_parser.add_argument("--verification-uri", required=True)
    claude_device_parser.add_argument("--verification-uri-complete")
    claude_device_parser.add_argument("--expires-in", type=int, required=True)
    claude_device_parser.add_argument("--interval", type=int, default=5)
    claude_device_parser.set_defaults(func=cmd_claude_device_card)

    orchestration_parser = subparsers.add_parser(
        "orchestration",
        help="Build auth orchestration plans, routed card payloads, and retry artifacts.",
    )
    orchestration_subparsers = orchestration_parser.add_subparsers(
        dest="orchestration_command",
        required=True,
    )

    orchestration_plan_parser = orchestration_subparsers.add_parser(
        "plan",
        help="Compare requested scopes against app and user grants, then batch missing scopes.",
    )
    orchestration_plan_parser.add_argument(
        "--requested-scope",
        action="append",
        default=[],
        required=True,
    )
    orchestration_plan_parser.add_argument("--app-scope", action="append", default=[])
    orchestration_plan_parser.add_argument("--user-scope", action="append", default=[])
    orchestration_plan_parser.add_argument("--batch-size", type=int, default=100)
    orchestration_plan_parser.add_argument("--keep-sensitive", action="store_true")
    orchestration_plan_parser.set_defaults(func=cmd_orchestration_plan)

    orchestration_route_parser = orchestration_subparsers.add_parser(
        "route",
        help="Map a structured auth requirement to a reusable card plan and continuation state.",
    )
    orchestration_route_parser.add_argument("--app-id", required=True)
    orchestration_route_parser.add_argument(
        "--error-kind",
        choices=["app_scope_missing", "user_auth_required", "user_scope_insufficient"],
        required=True,
    )
    orchestration_route_parser.add_argument(
        "--required-scope",
        action="append",
        default=[],
        required=True,
    )
    orchestration_route_parser.add_argument("--user-open-id")
    orchestration_route_parser.add_argument("--flow-key")
    orchestration_route_parser.add_argument("--operation-id")
    orchestration_route_parser.add_argument("--source")
    orchestration_route_parser.add_argument(
        "--token-type",
        choices=["tenant", "user"],
        default="user",
    )
    orchestration_route_parser.add_argument(
        "--scope-need-type",
        choices=["one", "all"],
        default="all",
    )
    orchestration_route_parser.add_argument("--permission-url")
    orchestration_route_parser.add_argument("--device-code", default="device-code")
    orchestration_route_parser.add_argument("--user-code", default="user-code")
    orchestration_route_parser.add_argument("--verification-uri", default="https://example.test/verify")
    orchestration_route_parser.add_argument("--verification-uri-complete")
    orchestration_route_parser.add_argument("--expires-in", type=int, default=600)
    orchestration_route_parser.add_argument("--interval", type=int, default=5)
    orchestration_route_parser.add_argument("--continuation-store-path")
    orchestration_route_parser.add_argument("--pending-flow-store-path")
    orchestration_route_parser.set_defaults(func=cmd_orchestration_route)

    orchestration_retry_parser = orchestration_subparsers.add_parser(
        "retry",
        help="Build a messenger-agnostic synthetic retry artifact from saved continuation state.",
    )
    orchestration_retry_parser.add_argument("--operation-id", required=True)
    orchestration_retry_parser.add_argument("--text", required=True)
    orchestration_retry_parser.add_argument("--reason", default="auth_completed")
    orchestration_retry_parser.add_argument("--continuation-store-path")
    orchestration_retry_parser.set_defaults(func=cmd_orchestration_retry)

    orchestration_verify_parser = orchestration_subparsers.add_parser(
        "verify-identity",
        parents=[common],
        help="Verify that an access token belongs to the expected open_id.",
    )
    orchestration_verify_parser.add_argument("--access-token", required=True)
    orchestration_verify_parser.add_argument("--expected-open-id", required=True)
    orchestration_verify_parser.set_defaults(func=cmd_orchestration_verify_identity)

    agent_parser = subparsers.add_parser(
        "agent",
        help="Normalize Feishu inbound messages and run a minimal native agent turn.",
    )
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)

    agent_parse_parser = agent_subparsers.add_parser(
        "parse-inbound",
        help="Normalize a Feishu inbound event into a stable message context envelope.",
    )
    agent_parse_parser.add_argument("--event-file", required=True)
    agent_parse_parser.set_defaults(func=cmd_agent_parse_inbound)

    agent_run_parser = agent_subparsers.add_parser(
        "run",
        help="Run a minimal native agent turn and emit a single-card step snapshot.",
    )
    agent_run_parser.add_argument("--event-file", required=True)
    agent_run_parser.add_argument("--runner", choices=["echo", "codex"], default="echo")
    agent_run_parser.add_argument("--system-prompt")
    agent_run_parser.add_argument("--session-id")
    agent_run_parser.add_argument("--echo-prefix", default="Echo")
    agent_run_parser.add_argument("--codex-bin", default="codex")
    agent_run_parser.add_argument("--model")
    agent_run_parser.add_argument("--codex-cd")
    agent_run_parser.add_argument("--codex-arg", action="append", default=[])
    agent_run_parser.add_argument("--timeout", type=int, default=180)
    agent_run_parser.add_argument("--emit-events", action="store_true")
    agent_run_parser.set_defaults(func=cmd_agent_run)

    agent_bind_parser = agent_subparsers.add_parser(
        "bind-continuation",
        help="Bind an existing continuation to a native retry contract.",
    )
    agent_bind_parser.add_argument("--operation-id", required=True)
    agent_bind_parser.add_argument("--text", required=True)
    agent_bind_parser.add_argument("--source")
    agent_bind_parser.add_argument("--continuation-store-path")
    agent_bind_parser.set_defaults(func=cmd_agent_bind_continuation)

    agent_action_parser = agent_subparsers.add_parser(
        "action-to-retry",
        help="Resolve a native card action into a retry turn request and artifact.",
    )
    agent_action_parser.add_argument("--operation-id", required=True)
    agent_action_parser.add_argument("--action", required=True)
    agent_action_parser.add_argument("--actor-open-id")
    agent_action_parser.add_argument("--message-id")
    agent_action_parser.add_argument("--payload-file")
    agent_action_parser.add_argument("--continuation-store-path")
    agent_action_parser.set_defaults(func=cmd_agent_action_to_retry)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
