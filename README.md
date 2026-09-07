# iMCP bridge plugin source

This directory is the source subtree for a Stavrobot plugin. It exposes tools
made available by a host-side iMCP HTTP bridge:

- `imcp_list_tools` lists tool names and input schemas.
- `imcp_call` forwards a tool name and JSON arguments and preserves the
  bridge's structured MCP result, error, and `truncated` fields.

## Publish and install

The public standalone plugin repository is
`https://github.com/diegopetrucci/stavrobot-imcp-plugin`. Install that URL in
Stavrobot. The plugin runner expects `manifest.json` at the root of the plugin
repository. Maintainers must publish the contents of this `plugin/imcp/`
directory as that standalone repository root; the monorepo URL is not itself a
directly installable plugin URL.

After installation, manually prepare the host bridge and configure `bridge_url`
and `bridge_token` through Stavrobot's web settings or the trusted host-side
secret/configuration path. Never paste `bridge_token` into agent chat.
`config.json.example` documents the expected shape for maintainers; the live
`config.json` is installation configuration and is ignored by git. The default
bridge URL is `http://host.docker.internal:8766/bridge`.

The tools send the token only as a Bearer credential and never include it in
output or error messages.

## Runner compatibility notes

`imcp_call` declares its `arguments` parameter as `type: "object"` deliberately.
The current plugin runner accepts unknown parameter types as a
forward-compatible schema behavior and skips primitive type validation for
that field, even though the current `PLUGIN.md` list documents only primitive
parameter types. The tool still validates that the received value is a JSON
object and defaults an omitted `arguments` value to `{}`.

The runner recognizes any exact top-level argument object shaped
`{"filename": ..., "data": ...}` as its `{filename,data}` file-transport
marker before invoking the tool. Therefore an MCP call whose entire top-level
`arguments` value has exactly those two keys collides with file materialization;
wrap those fields under another key when calling such an MCP tool.

The HTTP client uses a 20-second total wall-clock deadline: it is above the
bridge's 15-second outer deadline so the bridge can return its final response,
but below the synchronous runner's 30-second kill limit. The urllib socket
timeout is no greater than this total deadline. Tests are isolated from live
iMCP access and can be run from the repository root with:

```sh
./.venv/bin/python -m pytest -q plugin/imcp/tests
```
