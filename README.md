# iMCP bridge plugin for Stavrobot

Connects Stavrobot to [iMCP](https://github.com/mattt/iMCP), exposing approved
macOS-native services — Calendar, Contacts, Messages, Reminders, Location,
Maps, Weather, Shortcuts, and camera/audio/screenshot capture — through a
host-side authenticated bridge. Install it when a Stavrobot agent needs to
discover and use those native tools without putting personal-data access in a
group agent.

## Install

Tell Stavrobot to install
[`https://github.com/diegopetrucci/stavrobot-imcp-plugin`](https://github.com/diegopetrucci/stavrobot-imcp-plugin).
The operator must prepare the host bridge and its protected token and allowlist
before invoking a tool; the detailed, manual sequence is in
[`DEPLOY.md`](DEPLOY.md).

## Configuration

Configure these values through Stavrobot's trusted plugin settings or another
protected host-side configuration path. Never paste `bridge_token` into agent
chat.

### `bridge_url`

The HTTP URL of the host iMCP bridge.

Default: `http://host.docker.internal:8766/bridge`

The plugin runs inside `plugin-runner`, where `127.0.0.1` and `localhost` refer
to the container rather than the Mac host. Use `host.docker.internal` for the
host bridge.

### `bridge_token`

The Bearer token created by the operator for the host bridge. Store it only in
the protected host-side secret/configuration path. The tools use it only for
authentication and never include it in output or error messages.

## Tools

### `imcp_list_tools`

Lists the names and input schemas currently exposed by the authenticated
bridge. The result depends on the iMCP services enabled by the operator and
the host bridge allowlist.

### `imcp_call`

Forwards one exact iMCP tool name and a JSON object of arguments through the
authenticated bridge, preserving its structured result, error, and `truncated`
fields.

## Canonical repository and migration provenance

The official plugin bundle is the repository root: `manifest.json` must remain
at that root, alongside `_bridge.py`, `config.json.example`, `imcp_call/`, and
`imcp_list_tools/`. Do not publish or install a `plugin/imcp/` subtree as a
replacement for this root layout. This checkout also contains the host bridge
and operator source; preparing it does not install the plugin, create a token,
start a bridge, connect to live iMCP, or verify a Stavrobot deployment.

[`diegopetrucci/stavrobot-imcp`](https://github.com/diegopetrucci/stavrobot-imcp)
is the read-only predecessor retained as migration and rollback provenance.
The imported predecessor revision is the `chore/imcp-1.6-catch-up` branch from
[PR #4](https://github.com/diegopetrucci/stavrobot-imcp/pull/4), at
`6cff19f7b1d1f5bdd791892f476b79bf1cadff4b`. The predecessor `main` branch is
behind that revision by one commit and is not the source of the imported iMCP
1.6 catch-up. The predecessor is not an active publishing source and has not
been archived by this change; archive it only after consumers, deployment
configuration, and rollback checks have migrated to this repository. If
rollback is needed before then, keep it read-only and restore the last
known-good reviewed bundle and host revision using [`DEPLOY.md`](DEPLOY.md);
do not resume publishing from the predecessor.

## Component layout

The integration has separate host, plugin, and operator boundaries:

```text
iMCP app (macOS permissions and manual client approval)
  -> Bonjour discovery and forced-loopback MCP transport
  -> bridge/server.py at 127.0.0.1:8766/bridge (authenticated host bridge)
  -> host.docker.internal:8766/bridge (plugin-runner route)
  -> repository-root plugin contract (Stavrobot plugin bundle)
  -> Stavrobot plugin tools and the approved agent
```

- `bridge/server.py` owns the authenticated HTTP boundary and keeps the
  discovered iMCP connection on loopback. See [`bridge/README.md`](bridge/README.md)
  for its request and response contract.
- The plugin tools are `imcp_list_tools` and `imcp_call`. Host-only source is
  co-located under `bridge/`, `stavrobot_imcp/`, and `scripts/`; it is not part
  of the plugin tool contract. See [`MAINTAINING.md`](MAINTAINING.md).
- The bridge token, host allowlist, and installed plugin configuration are
  separate operator-managed configuration. Keep credentials out of this
  repository, agent chat, command output, and logs. If the live host allowlist
  contains `*`, a future iMCP release can add newly exposed tools without any
  allowlist edit; review release notes and a fresh read-only `tools/list` result
  before relying on that expanded surface. This documentation does not change
  the live allowlist.

## Python 3.14 setup and local verification

From the repository root, create the explicit Python 3.14 environment and
install the pinned dependencies:

```sh
python3.14 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Run the local suite with:

```sh
./.venv/bin/python -m pytest -v
```

The suite includes [`tests/test_bridge_sdk.py`](tests/test_bridge_sdk.py),
which uses the official MCP Python SDK against a local newline-delimited
fixture. It verifies initialization and readiness cancellation, setup and
in-flight cancellation, reconnect after disconnect without replaying a call,
and idle/in-flight cleanup. These are local fixture checks only; they do not
start the installed iMCP app, invoke a live iMCP tool, or verify network access
from Stavrobot `plugin-runner`.

## Short operator path

For startup after login and automatic bridge crash recovery, prepare the token
and allowlist, then run:

```sh
./.venv/bin/python scripts/install_login_services.py
```

This installs a bridge LaunchAgent and an iMCP app login LaunchAgent. The
login-service prerequisite is an already-installed app at
`/Applications/iMCP.app`; this repository only opens it and does not install
or copy the app. The bridge restarts after exits with a 30-second throttle.
The tmux helper (`scripts/start-stavrobot-imcp-bridge`) and the bridge
LaunchAgent are mutually exclusive supervisors: running both on
`127.0.0.1:8766` causes port-conflict retries and log growth. Stop one
supervisor before starting the other. See the login-startup section in
`DEPLOY.md` for configuration checks and uninstall instructions. After a
reboot, the Mac must be unlocked and the user logged in; this is not a
pre-login daemon.

For an approved deployment, use this sequence rather than treating local tests
as deployment evidence:

1. Read [`DEPLOY.md`](DEPLOY.md), including its safety gates. Select only the
   required iMCP services and permissions, keep the bridge on
   `127.0.0.1:8766`, create the protected token and explicit tool allowlist in
   a trusted host terminal, start the host bridge as directed, and manually
   approve the first iMCP client connection. Start with an approved read-only
   operation.
2. Follow [`MAINTAINING.md`](MAINTAINING.md), then publish the repository
   root as the standalone plugin URL or copy only the root plugin contract
   files (`manifest.json`, `_bridge.py`, `config.json.example`, `imcp_call/`,
   and `imcp_list_tools/`) into the installed plugin bundle. Configure its
   `bridge_url` and `bridge_token` through Stavrobot's trusted settings path.
   The plugin URL uses `host.docker.internal:8766`;
   `127.0.0.1` inside `plugin-runner` is the container, not the host.
3. Follow [DEPLOY.md's plugin-runner reachability checks](DEPLOY.md#6-required-reachability-verification-from-plugin-runner).
   The authenticated check must run from the actual `plugin-runner` as the
   dedicated plugin user. Do not widen the host bind to `0.0.0.0` to work
   around a failed container check, and keep iMCP excluded from every
   `telegram-group-*` agent.

The operator sequence above is not evidence that installation or live
verification has occurred. The deployment runbook remains the source of truth
for manual approvals, secret handling, rollback, and live iMCP/Stavrobot
verification.

## Host bridge command (operator instruction)

The host bridge is authenticated and host-only. Once the manual prerequisites
in [`DEPLOY.md`](DEPLOY.md) are complete, run the repository helper from its
root:

```sh
scripts/start-stavrobot-imcp-bridge
```

The helper requires the protected token at `~/.config/imcp-bridge.token` and a
non-empty, owner-only allowlist at `~/.config/imcp-bridge-tools.json`. It passes
both paths with `--token-file` and `--allowlist-file`, and starts the bridge on
`127.0.0.1:8766/bridge` with the required `--call-timeout 10` setting. It accepts
JSON `POST` operations for `health`, `list_tools`, and `call_tool`. This command
is documentation only;
it was not run as part of authoring this README, and repository setup and tests
do not start a persistent bridge.

## Secondary feature: metadata probe

The original read-only metadata probe remains available as a secondary
feature, separate from the bridge/plugin deployment. After enabling only the
approved iMCP services and completing any macOS permission prompts, run it in
the logged-in macOS session:

```sh
./.venv/bin/python scripts/probe_imcp.py --timeout 300
```

When iMCP shows its Connection Request window, approve the client manually.
The probe performs the MCP handshake and requests only `tools/list`; it never
invokes an MCP tool. It uses the shared Bonjour-discovered loopback transport
and writes only tool names, descriptions, and input schemas to
`docs/imcp-tools.md`. By default, the recorded app version is read from the
selected app's `Contents/Info.plist` `CFBundleShortVersionString`. Use
`--app-version VERSION` to explicitly override it. Without an override,
missing or invalid version metadata causes the probe to fail rather than
record a guessed version. Before connecting, the probe compares the running
iMCP process's canonical executable path and device/inode identity with the
selected app, and checks the same PID and identity again after `tools/list`.
After a Sparkle update or rollback, manually quit and relaunch iMCP before
capture; the probe refuses a different or stale process and never terminates
or relaunches one automatically.

## Remove the local environment

To undo the local virtual-environment setup, run:

```sh
rm -rf .venv
```

This removes only the repository's ignored virtual environment. Re-run the
setup commands above to recreate it.
