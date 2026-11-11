# iMCP host bridge

`server.py` is a macOS-host HTTP boundary around the bundled
`/Applications/iMCP.app/Contents/MacOS/imcp-server` stdio transport and the
official Python MCP SDK. It requires iMCP **1.8.2 or newer** and is not
installed, launched, or registered as a persistent service by this repository.
The plugin-facing HTTP contract remains independent of this host transport.

Optional `--client-credential-file` (default helper path `~/.config/imcp-client.credential`, mode 0400/0600) supplies the client credential iMCP 1.8.2+ shows after you approve the client with "Always trust this client". The bridge pings a reused session before each request and relaunches `imcp-server` if it exited; it never replays a call.

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
The bridge launches a fresh bundled `imcp-server` child for each new MCP
session without a shell. Stdio startup has a 5-second default bound; MCP
initialization and tool operations use the configured 10-second default read
bound. The HTTP bridge gives the complete operation—including stdio startup,
MCP initialization, and tool dispatch—a 15-second default runtime deadline
(the configured call timeout plus 5 seconds), comfortably before the plugin
client's 20-second limit and the synchronous plugin-runner's 30-second limit.
Each phase is capped by the remaining outer deadline. Stdio shutdown uses the
SDK's bounded 6.5-second escalation sequence; the bridge's 7-second shutdown
floor and 18-second runtime-close budget leave room for orderly teardown. This
invariant imposes a strict `<11s` ceiling on `--call-timeout`
(`call timeout + shutdown timeout < 18s`); the default remains 10 seconds.

The MCP session is persistent after first use and reconnects lazily. A
reconnect starts a new `imcp-server` process and MCP context; it does not reuse
or rediscover a TCP endpoint. If iMCP displays a **Connection Request** for the
bridge client `stavrobot-imcp-bridge`, review and approve it manually. A
remembered approval may make later launches prompt-free, but a missing prompt
is not proof that the app is ready. If a session is already known dead before
dispatch, the next request may reconnect. If a `tools/call` may have been
dispatched and then loses its response, the bridge returns
`error.code: "unknown_outcome"`, marks the session dead, and never replays the
call. A later request can establish a fresh session; retry only a read-only
listing after resolving an approval or startup timeout.

The CLI configures INFO operational logging. Logs contain only a bounded tool
name, status, and duration. Arguments, results, tokens, and child-process
output are not logged.
