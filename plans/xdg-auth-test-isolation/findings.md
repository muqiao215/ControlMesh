# Findings

## Confirmed Facts

- Two tests in `tests/cli/test_auth.py` failed by returning the operator's real
  `~/.local/share/opencode/auth.json` path instead of a temporary path.
- Both passed when `XDG_DATA_HOME` and `XDG_CONFIG_HOME` were removed from the test command.
- Production code intentionally honors explicit XDG roots before defaults based on
  `Path.home()`.
- `tests/cli/test_auth.py` had no shared environment-isolation fixture. Individual tests
  sometimes removed `XDG_CONFIG_HOME`, but none removed inherited `XDG_DATA_HOME`.
- Existing tests that intentionally exercise an XDG override call `monkeypatch.setenv`
  inside the test, so a module-level autouse cleanup fixture will not weaken that coverage.

## Open Questions

- Does the full suite expose any other ambient provider-auth environment dependencies?

## Decisions

| Decision | Rationale |
|---|---|
| Scope the fix to tests unless contrary evidence appears | Current evidence identifies ambient environment leakage, not a runtime defect. |
| Clear both XDG variables in an autouse fixture for this test module | Every auth test starts hermetically, while tests can still set an explicit override after fixture setup. |
