# iMCP host bridge

`server.py` is a macOS-host HTTP boundary around the shared Bonjour/loopback
transport and the official Python MCP SDK. It is not installed, launched, or
registered as a persistent service by this repository.

## Reproducible setup

From the repository root:

```sh
python3.14 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Run the focused checks without live iMCP access:

```sh
./.venv/bin/python -m pytest -v tests/test_bridge.py
```

## Startup configuration

```sh
./.venv/bin/python bridge/server.py \
  --token-file ~/.config/imcp-bridge.token \
  --bind 127.0.0.1 --port 8766 --path /bridge \
  --allowlist-file ~/.config/imcp-bridge-tools.json
```

The default allowlist is `*`. A trusted allowlist file is JSON in either of
these forms:

```json
["calendar_list", "reminders_list"]
```

or:

```json
{"tools": ["calendar_list", "reminders_list"]}
```

`--allow-tool` may be repeated and overrides the file. Allowlist checks happen
before an MCP session is opened or a tool is dispatched.

## HTTP operations

All requests use the configured path and `Authorization: Bearer <token>`.
`POST` bodies are JSON objects:

```json
{"operation": "health"}
{"operation": "list_tools"}
{"operation": "call_tool", "name": "calendar_list", "arguments": {}}
```

Responses retain an object envelope:

```json
{"ok": true, "result": {"...": "..."}, "truncated": false}
```

`health` reports `bridge_up`, `mcp_session_up`, and
`imcp_app_reachable` separately. Before the first connection attempt,
`imcp_app_reachable` is JSON `null` (unknown); after an attempt it is `true` or
`false` based on the latest connection evidence. Health reads runtime-owned
state without waiting for an in-flight MCP operation. `list_tools` follows
bounded MCP pagination and returns the allowlisted tool metadata. `call_tool`
returns the SDK result unchanged in `result`, including
`content`, `structuredContent` (JSON-LD), and `isError`. MCP protocol errors
retain their numeric code and structured `data` under `error`.

Request bodies are limited to 64 KiB and responses to 256 KiB. Oversized
responses are valid JSON with `truncated: true`; they are structurally pruned
while retaining result semantics such as `isError` and the structured
`structuredContent` key when present, never cut at an arbitrary byte boundary.
MCP operations use a bounded server call timeout (10 seconds by default).
A cold session setup has a separate 9-second default bound: one 3-second
Bonjour observation window, up to a second 3-second service-detail resolution
window, and a 3-second TCP connect. The HTTP bridge gives the complete
operation—including cold setup, MCP initialization, and tool dispatch—a
15-second default runtime deadline (the configured call timeout plus 5
seconds), comfortably before the downstream synchronous plugin's current
20-second limit. Each phase is also capped by the remaining outer deadline.

The MCP session is persistent after first use and reconnects lazily. Each
reconnect creates a new shared-transport context, causing fresh Bonjour port
discovery; advertised interface addresses are discarded and the TCP connection
is made only to `127.0.0.1:<discovered-port>`. If a session is already known
dead before dispatch, the next request may reconnect. If a `tools/call` may
have been dispatched and then loses its response, the bridge returns
`error.code: "unknown_outcome"`, marks the session dead, and never replays the
call. A later request can establish a fresh session.

The CLI configures INFO operational logging. Logs contain only a bounded tool
name, status, and duration. Arguments, results, tokens, and discovered host
details are not logged.
