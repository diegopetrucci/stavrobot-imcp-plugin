# Maintaining the iMCP bridge plugin

This file covers maintainer-only information for the iMCP bridge plugin.
The plugin bundle lives at `plugin/imcp/` in the `stavrobot-imcp` monorepo
and is published at the root of the
`https://github.com/diegopetrucci/stavrobot-imcp-plugin` repository.
It covers publishing the standalone plugin repository, configuration shape,
runner compatibility notes, and how to run the tests.

## Publishing the standalone repository

The plugin runner expects `manifest.json` at the root of the plugin repository.
Maintainers must publish the contents of the monorepo's `plugin/imcp/`
directory as the standalone repository root at
`https://github.com/diegopetrucci/stavrobot-imcp-plugin`. The monorepo URL is
not itself a directly installable plugin URL.

`config.json.example` documents the expected configuration shape for
maintainers; the live `config.json` is installation configuration and is ignored
by git.

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
timeout is no greater than this total deadline.

## Running the tests

Tests are isolated from live iMCP access.

**In the monorepo** (from the `stavrobot-imcp` root):

```sh
./.venv/bin/python -m pytest -q plugin/imcp/tests
```

**In the standalone repository** (from its root):

```sh
python -m pytest -q tests
```
