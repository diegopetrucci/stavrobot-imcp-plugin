# Maintaining the iMCP bridge plugin

This repository is the sole active source of truth for both the Stavrobot
plugin and its host-side iMCP bridge. The plugin contract remains at the
repository root:
`manifest.json`, `_bridge.py`, `config.json.example`, `imcp_call/`, and
`imcp_list_tools/`. Host runtime code is maintained alongside it under
`bridge/`, `stavrobot_imcp/`, and `scripts/`.

## Canonical ownership and migration provenance

The supported install URL is
`https://github.com/diegopetrucci/stavrobot-imcp-plugin`. The plugin runner
requires `manifest.json` at the root of the installable bundle. Publish or
install this repository root; do not restore the former `plugin/imcp/` subtree
layout or publish a host-bridge-only checkout. Keep the root manifest and the
root plugin directories in place when changing the co-located host source.

`https://github.com/diegopetrucci/stavrobot-imcp` is the read-only predecessor
for the migration. The imported predecessor revision is the
`chore/imcp-1.6-catch-up` branch from
[PR #4](https://github.com/diegopetrucci/stavrobot-imcp/pull/4), at
`6cff19f7b1d1f5bdd791892f476b79bf1cadff4b`. The predecessor `main` branch is
behind that branch by one commit and is not the source of the imported iMCP 1.6
catch-up. Keep this branch/SHA as exact provenance; do not silently substitute
predecessor `main` when reviewing or restoring the migration.

The predecessor remains available as a rollback reference, is not an active
publishing source, and has not been archived by this change. Archive it only
after consumers, deployment configuration, and rollback checks have migrated
to this repository. Until then, keep it read-only. If a rollback is required,
restore the last known-good reviewed plugin bundle and host revision using the
deployment runbook; do not publish a rollback from the predecessor. The
existing-deployment reconciliation required before archival is documented in
[`DEPLOY.md`](DEPLOY.md#existing-predecessor-deployment-reconciliation-before-archival).

The live `config.json` is installation configuration and is ignored by git.
Never copy it, credentials, caches, or other local configuration into source
control.

## Runner compatibility notes

`imcp_call` declares its `arguments` parameter as `type: "object"` deliberately.
The current plugin runner accepts unknown parameter types as a
forward-compatible schema behavior and skips primitive type validation for
that field, even though the current `PLUGIN.md` list documents only primitive
parameter types. The tool still validates that the received value is a JSON
object and defaults an omitted `arguments` value to `{}`.

The runner recognizes any exact top-level argument object shaped
`{"filename": ..., "data": ...}` as its `{filename,data}` file-transport marker
before invoking the tool. Therefore an MCP call whose entire top-level
`arguments` value has exactly those two keys collides with file materialization;
wrap those fields under another key when calling such an MCP tool.

The HTTP client uses a 20-second total wall-clock deadline: it is above the
bridge's 15-second outer deadline so the bridge can return its final response,
but below the synchronous runner's 30-second kill limit. The urllib socket
timeout is no greater than this total deadline.

## Running the tests

Tests are isolated from live iMCP access. From the repository root, use the
existing Python 3.14 environment when available:

```sh
./.venv/bin/python -m pytest -q tests/test_tools.py
```

Run the host-focused checks with:

```sh
./.venv/bin/python -m pytest -q tests/test_bridge.py tests/test_bridge_sdk.py tests/test_transport.py tests/test_check_bridge.py tests/test_create_token.py tests/test_login_service.py tests/test_probe_imcp.py
```

Run the complete suite with:

```sh
./.venv/bin/python -m pytest -q
```

`.github/workflows/ci.yml` runs that complete command in a fresh Python 3.14
virtual environment after installing `requirements.txt`.

The tests use local fixtures and mocks only; they do not start the installed
iMCP app, invoke a live iMCP tool, or verify network access from Stavrobot
`plugin-runner`.
