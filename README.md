# iMCP bridge plugin for Stavrobot

Connects Stavrobot to [iMCP](https://github.com/mattt/iMCP), exposing macOS-native services — Calendar, Contacts, Messages, Reminders, Location, Maps, Weather, Shortcuts, and Camera/audio/screenshot capture — to the assistant through a host-side authenticated bridge.

## Prerequisites

- A Mac running the iMCP app with the services you want enabled.
- The host iMCP bridge running and reachable from the Stavrobot plugin-runner (the operator prepares this on the host before installing the plugin).
- A bridge token and tool allowlist created on that host.

## Install

Tell Stavrobot to install `https://github.com/diegopetrucci/stavrobot-imcp-plugin`

## Configuration

### `bridge_url`

The HTTP URL of the host iMCP bridge.

Default: `http://host.docker.internal:8766/bridge`

Note: `127.0.0.1` inside the plugin-runner resolves to the container, not the host. Use `host.docker.internal` so the request reaches the Mac.

### `bridge_token`

The Bearer token the operator created for the bridge, stored in the host's protected token file.

Configure `bridge_token` through Stavrobot's web settings or the trusted host-side secret path, never by pasting it into agent chat.

The tools send the token only as a Bearer credential and never include it in output or error messages.

## Tools

### `imcp_list_tools`

Reports the tool names and input schemas the bridge currently exposes. The available tools depend on which iMCP services the operator enabled and which tools are on the bridge allowlist.

### `imcp_call`

Forwards a tool name and JSON arguments to the bridge and returns the bridge's structured MCP result, including `error` and `truncated` fields.
