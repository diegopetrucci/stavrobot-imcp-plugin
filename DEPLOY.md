# iMCP bridge and Stavrobot plugin deployment

This is a **manual operator runbook**. The repository contains source and
templates only. Preparing this checkout does not create a token, copy files
outside the repository, change chezmoi, install the plugin, load a LaunchAgent,
start a bridge, run Docker/OrbStack, or invoke an iMCP tool.

The bridge exposes an authenticated HTTP boundary for the iMCP services enabled
by the operator:

```text
iMCP app (>=1.8.2; macOS permissions and client approval)
  -> bundled Contents/MacOS/imcp-server over stdio
  -> 127.0.0.1:8766/bridge (authenticated host bridge)
  -> host.docker.internal:8766/bridge (plugin-runner)
  -> Stavrobot imcp plugin
```

## Safety gates

1. Obtain explicit human approval for the services, tools, agents, and first
   read-only test operation. iMCP can expose personal calendar, contacts,
   messages, reminders, location, maps, and weather data; enable only the
   services that have been selected. The bundled stdio entrypoint is supported
   only by iMCP **1.8.2 or newer**; verify the selected app version and
   `Contents/MacOS/imcp-server` before starting the bridge.
2. Keep the bridge bound to `127.0.0.1` and use the fixed HTTP bridge port
   `8766`. Do **not** change the bind to `0.0.0.0` automatically if the
   container check fails. Stop and diagnose the host-gateway path instead.
3. Keep the bridge token out of agent chat, shell output, logs, commits, and
   this repository. The host token file, the host allowlist, and the installed
   plugin `config.json` are separate configuration; the first and last may be
   secret-bearing, and none belongs in source.
4. Use a trusted host allowlist with explicit iMCP tool names. Although
   `bridge/server.py` defaults to `*` when no allowlist is supplied, deployment
   through the helper or LaunchAgent wrapper below requires
   `~/.config/imcp-bridge-tools.json` so least privilege is deliberate.
5. Keep the timeout ladder intact:
   `15s (bridge) < 20s (plugin client) < 30s (synchronous plugin-runner)`.
   The bundled stdio startup has a separate 5-second bound, and the helper and
   LaunchAgent wrapper explicitly pin the bridge's 10-second `--call-timeout`
   default, which yields its 15-second outer deadline. The SDK's stdio shutdown
   escalation is bounded at 6.5 seconds, with a 7-second configuration floor.
   The 18-second runtime-close invariant therefore imposes a strict `<11s`
   ceiling on `--call-timeout` (`call timeout + shutdown timeout < 18s`); a
   larger shutdown setting lowers that ceiling. Any override must keep the
   resulting bridge outer deadline strictly below the plugin's 20 seconds and
   leave enough time for stdio teardown.
6. Use exactly one supervisor at a time: either the tmux start helper or the
   direct LaunchAgent template below. Running both causes a collision on
   `127.0.0.1:8766`.

## Prerequisites and virtual environment

The stdio migration requires an installed iMCP app at version **1.8.2 or
newer** with its bundled server executable. Check both before preparing the
bridge; do not continue with an older app or a missing executable:

```sh
mdls -name kMDItemVersion -raw /Applications/iMCP.app
test -x /Applications/iMCP.app/Contents/MacOS/imcp-server
```

In a trusted local terminal, prepare the checkout and its explicit Python
virtual environment. These commands are instructions for a later operator;
they were not run as part of authoring this runbook:

```sh
cd "$HOME/Developer/stavrobot-imcp-plugin"
python3.14 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

The start helper and plist intentionally invoke
`$HOME/Developer/stavrobot-imcp-plugin/.venv/bin/python`, not whichever `python3` an
interactive shell happens to select. If the checkout is elsewhere, render or
adapt the paths deliberately rather than adding a second, untracked runtime.

## 1. Manually prepare iMCP and macOS permissions

All prompts and approvals in this section are manual:

1. Open the installed iMCP app in the logged-in macOS user session and verify
   that it is **1.8.2 or newer** with the executable checked in the prerequisite
   section above.
2. Enable only the agreed iMCP services. Do not infer availability from an
   upstream source checkout or from an old tool list.
3. In **System Settings > Privacy & Security**, grant only the macOS access
   required by those services. Complete any iMCP-native permission flow. For
   Messages history, use the app's documented file-selection flow if it asks
   for access; this integration does not describe or test message sending.
4. Start the bridge after the app is ready. The first authenticated
   `list_tools` request launches the bundled `imcp-server` over stdio. iMCP may
   display a **Connection Request** window for the client named
   `stavrobot-imcp-bridge`; review the client and approve it manually. A
   remembered approval may suppress later prompts, but a missing prompt is not
   proof that permissions or client trust are correct. Check the app's
   remembered-client and service settings.
5. Use a disposable, read-only operation for the first end-to-end test. Do not
   use a write, delete, message, reminder, or calendar mutation as a health
   check.

A macOS permission prompt must not be left waiting inside a synchronous
Stavrobot tool call. Resolve the prompt before the plugin-runner verification.

## 2. Create the host token securely (operator action only)

Generate the token in a trusted local terminal, never in agent chat. The
checkout and an available Python 3 interpreter are prerequisites; the helper
uses only Python's standard library and creates the configuration directory if
needed:

```sh
cd "$HOME/Developer/stavrobot-imcp-plugin"
./scripts/create_token.sh
```

The helper writes `~/.config/imcp-bridge.token` without printing its contents,
uses mode `0600`, and refuses symlink, nonregular, empty, or invalid existing
token files. Repeating the command preserves an existing valid token and reapplies
owner-only permissions; it does not rotate or overwrite credentials. If this
command newly created the token and you need to undo only that creation, first
confirm it did not exist before the command, then remove it from the trusted
terminal:

```sh
rm "$HOME/.config/imcp-bridge.token"
```

Deleting the token file does not immediately revoke a credential from a
running bridge: the bridge retains its startup credential in memory until its
active supervisor is stopped. Stop the tmux supervisor or boot out the
LaunchAgent before deleting or replacing the token. If the token is deleted
first, the running bridge remains live; after it exits, the `KeepAlive`
LaunchAgent cannot pass preflight and retries every 30 seconds, causing
continued log growth until that job is booted out. Do not use deletion as a
rotation procedure; an approved rotation must stop the active supervisor,
update the host file and Stavrobot plugin configuration together, then start
one supervisor again. Never use `cat` on the token in a chat or log, and do not
put its value in the plist, `config.json.example`, a command transcript, or
Git.

Create the separate host allowlist in the same trusted terminal. Use a JSON
object with only the exact, approved iMCP tool names; never use `*` for a
least-privilege deployment. This example selects two read-only tools and is a
configuration example, not an instruction to enable services that were not
approved:

```sh
allowlist_file="$HOME/.config/imcp-bridge-tools.json"
if [ ! -s "$allowlist_file" ]; then
  ( umask 077
    mkdir -p "${allowlist_file%/*}"
    cat > "$allowlist_file" <<'JSON'
{"tools":["calendars_list","reminders_lists"]}
JSON
  )
fi
chmod 600 "$allowlist_file"
```

Replace those example names with the exact names selected by the operator
(for example, after reviewing the read-only `tools/list` metadata), keeping the
list explicit and excluding every unapproved read or write tool. The start
helper refuses a missing, empty, unreadable, or group/other-accessible allowlist
and enforces its owner-only mode; it passes this file with `--allowlist-file` to
the bridge. The direct plist invokes `scripts/run_launchd_bridge.py`, whose private
configuration preflight runs before it execs `bridge/server.py` and enforces
these file modes.
The allowlist contains no credential, but keep it owner-only so it cannot be
silently broadened by another account.

### 2.1 Tiered allowlist guidance (iMCP 1.8.x)

Group tools into tiers and opt in explicitly, one tool name at a time. Verify
names against the installed app's `tools/list` (`scripts/probe_imcp.py`); this
list reflects iMCP 1.8.3.

- **Read-only tier** (reasonable starting point once the service is approved):
  `calendars_list`, `events_fetch`, `contacts_list`, `contacts_me`,
  `contacts_search`, `messages_fetch`, `reminders_fetch`, `reminders_lists`,
  `phone_calls_fetch`, `voicemails_fetch`, `voicemail_transcript_fetch`,
  `mail_mailboxes_list`, `mail_messages_search`, `mail_messages_read`,
  `notes_folders`, `notes_fetch`, `notes_read`, `voice_memos_fetch`,
  `voice_memo_transcript_fetch`, `music_now_playing`, `music_catalog_search`,
  `location_current`, `location_geocode`, `location_reverse-geocode`, `maps_search`, `maps_directions`,
  `maps_eta`, `maps_explore`, `maps_generate`, `weather_current`,
  `weather_hourly`, `weather_daily`, `weather_minute`, `shortcuts_list`, and
  the Home read tools (`homes_list`, `home_export`, `rooms_list`, `zones_list`,
  `accessories_list`, `accessories_get`, `characteristics_read`,
  `scenes_list`, `automations_list`). `messages_attachment_read`,
  `voicemail_audio_fetch` and `voice_memo_audio_fetch` return large binary data
  (see limits below) and are sensitive even though they are reads.
- **Write / side-effect tier** (enable only with explicit approval per tool):
  `events_create`, `events_update`, `events_delete`, `contacts_create`,
  `contacts_update`, `reminders_create`, `reminders_update`,
  `reminders_delete`, `reminders_lists_create`, `reminders_lists_rename`,
  `reminders_lists_delete`, `mail_compose` (opens a draft), `music_control`,
  `phone_call`, `shortcuts_run`, `utilities_beep`, the capture tools
  (`capture_take_picture`, `capture_record_audio`, `capture_take_screenshot`),
  and every Home write tool (`characteristics_write`, `scenes_execute`,
  `scenes_create`/`_update`/`_remove`, `automations_create`/`_update`/`_remove`,
  `accessories_identify`/`_rename`/`_assign_room`/`_remove`, `services_rename`,
  `rooms_create`/`_rename`/`_remove`, `zones_create`/`_update`/`_remove`). Delete/remove
  tools are destructive. `shortcuts_run` can do anything the shortcut does.

Never use `*`. Do not use a write-tier tool as a health check.

### 2.2 Limits and folder access

- The bridge caps each response at 256 KiB and each call at 10 seconds. Large
  binary results (voicemail and voice-memo audio, message attachments, camera
  or screenshot captures) may be truncated (`truncated: true`) or fail; text
  results and transcripts work.
- Mail, Notes, Voice Memos, Voicemail, and Messages attachments need folder
  access granted inside iMCP (its service settings) in addition to macOS
  privacy permissions. Home requires the self-signed iMCP Helper to be paired
  per the upstream iMCP README.

## 3. Start the host bridge

The in-repository helper is `scripts/start-stavrobot-imcp-bridge`. It sets the
non-interactive Homebrew/Python `PATH`, checks the explicit venv Python,
protected token file, and owner-only allowlist, uses the tmux session named
exactly `stavrobot-imcp-bridge`, and starts with `--call-timeout 10` and:

```text
127.0.0.1:8766/bridge
```

Run it manually from the checkout after the iMCP service and macOS permission
prerequisites are complete. Client approval is deliberately the next step in
§3.1, triggered by the authenticated host-side `list_tools` request:

```sh
cd "$HOME/Developer/stavrobot-imcp-plugin"
chmod +x scripts/start-stavrobot-imcp-bridge
scripts/start-stavrobot-imcp-bridge
```

The helper only manages its exact reserved tmux session. Repeating a successful
start converges on one session; it does not kill other tmux sessions or print
`lsof` details. If the fixed port is already owned by a process without that
session, it fails clearly and leaves the existing listener alone. Do not work
around that error by changing the bridge port or exposing another interface.
The helper passes `--allowlist-file ~/.config/imcp-bridge-tools.json` and
`--call-timeout 10`; do not remove either safety boundary. The bridge launches
`/Applications/iMCP.app/Contents/MacOS/imcp-server` as a local child over stdio
on demand. There is no iMCP TCP port to configure, discover, expose, or add to
logs; only the fixed authenticated HTTP bridge endpoint is part of the plugin
contract.

### 3.1 Trigger the first host-side MCP connection and approve it manually

After the bridge is listening, run this **on the macOS host**, not in
`plugin-runner`. It sends exactly one authenticated, read-only `list_tools`
POST to the fixed bridge endpoint. The repository helper reads the token file
internally, keeps it in memory, uses a direct no-proxy/no-redirect HTTP
connection, bounds the response read, and prints only generic status messages.
It therefore triggers iMCP's client request for `stavrobot-imcp-bridge` without
putting the token, response body, or tool metadata in a command argument or
output:

```sh
cd "$HOME/Developer/stavrobot-imcp-plugin"
./scripts/check_bridge.sh
```

The helper prints conditional approval guidance before waiting. Watch iMCP
while this command waits and approve the **Connection Request** only if iMCP
shows it. If no prompt appears, a successful listing needs no further approval.
The bridge's 15-second outer deadline is shorter than this client's 20-second
socket timeout. If the first read-only request expires at 15 seconds (or
reaches the 20-second client timeout), wait for the command to exit and rerun
`./scripts/check_bridge.sh` after resolving the approval. Rerunning this
read-only discovery request is safe; do not generalize that retry rule to a
`call_tool` whose outcome could be unknown. The helper never invokes an iMCP
tool and never retries automatically.

The bridge keeps a successful MCP session open for later requests. If iMCP or
`imcp-server` exits, the next request reconnects lazily by launching a fresh
stdio child; it does not replay a call. If a `call_tool` may have been
dispatched before its response was lost, treat `error.code: "unknown_outcome"`
as non-retryable and inspect the app before any further action. A later
read-only `list_tools` request can establish the fresh session after approval
or startup recovery.

The unauthenticated GET in §6.1 is only a route/authentication check. It cannot
trigger iMCP client approval because the bridge rejects it before opening an
MCP session.

## 4. Copy or publish the plugin source bundle

The canonical repository root contains the standalone Stavrobot plugin
contract alongside the host bridge source. The **preferred and supported
installation is URL installation** from the public repository:
`https://github.com/diegopetrucci/stavrobot-imcp-plugin`. Its root contains
`manifest.json`, `_bridge.py`, `config.json.example`, `imcp_call/`, and
`imcp_list_tools/`, so the published repository URL is the installable plugin
URL; there is no separate plugin source subtree.

For each release, maintainers publish the reviewed repository root and verify
the root manifest before publishing. Exclude local configuration, caches, and
credentials; this is publication guidance only and does not automate
synchronization.

For a deliberately local installation, an operator may copy only the root
plugin contract files to the Stavrobot checkout's plugin data directory. Do
not copy the live configuration from another installation and do not run this
during repository authoring:

```sh
STAVROBOT_ROOT="/path/to/stavrobot"
PLUGIN_SOURCE="$HOME/Developer/stavrobot-imcp-plugin"
mkdir -p "$STAVROBOT_ROOT/data/plugins/imcp"
rsync -a \
  --exclude config.json \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$PLUGIN_SOURCE/manifest.json" \
  "$PLUGIN_SOURCE/_bridge.py" \
  "$PLUGIN_SOURCE/config.json.example" \
  "$PLUGIN_SOURCE/imcp_call" \
  "$PLUGIN_SOURCE/imcp_list_tools" \
  "$STAVROBOT_ROOT/data/plugins/imcp/"
```

A local copy is not complete when `rsync` finishes. It requires a **controlled
`plugin-runner` restart** so its startup migration creates the dedicated
`plug_imcp` user and chowns the bundle to that user. This restart is an
operator action that requires an intentionally available deployment:

```sh
cd /path/to/stavrobot
docker compose restart plugin-runner
```

After the restart, verify the actual mounted `/plugins` directory, the bundle
path, and ownership from inside `plugin-runner` before configuring or invoking
the tools. Do not print `config.json`:

```sh
docker compose exec -T plugin-runner sh -c '
  id plug_imcp
  test -d /plugins
  test -f /plugins/imcp/manifest.json
  stat -c "%U:%G %a %n" /plugins /plugins/imcp /plugins/imcp/manifest.json
'
```

If the runner reports a different bundle path, use that actual path for the
later smoke command and verify its files are owned by `plug_imcp`; do not
silently run the bundle as root. A supported URL install still requires the
same post-install `/plugins` and ownership check.

The resulting layout is:

```text
$STAVROBOT_ROOT/data/plugins/imcp/
├── manifest.json
├── _bridge.py
├── config.json.example         # published setup documentation
├── config.json                 # created/configured after install; secret
├── imcp_list_tools/
│   ├── manifest.json
│   └── run.py
└── imcp_call/
    ├── manifest.json
    └── run.py
```

`config.json.example` is documentation, not a live configuration. Keep the
installed `config.json` out of Git and do not return it through an agent tool.
If the plugin is installed through Stavrobot instead of copied, confirm that
the plugin runner created the same layout before proceeding.

## Existing predecessor deployment reconciliation before archival

This section is a documented, later operator procedure. This ticket does not
run `launchctl`, install or boot out a LaunchAgent, run `chezmoi apply`, or
change any live deployment. Do not archive or delete the predecessor checkout
until the existing deployment has been reconciled deliberately.

The predecessor checkout is `~/Developer/stavrobot-imcp`. Treat the following
as potentially dependent on that checkout until they have been inspected:

- the deployed bundle at `~/Developer/misc/stavrobot/data/plugins/imcp/` and its
  separately managed `config.json` (never print or copy that file);
- the per-user jobs `com.stavrobot.imcp` (the bridge) and
  `com.stavrobot.imcp-app` (opens iMCP), including any rendered files under
  `~/Library/LaunchAgents/`; and
- the chezmoi source entries
  `~/.local/share/chezmoi/private_Library/LaunchAgents/com.stavrobot.imcp.plist.tmpl`
  and
  `~/.local/share/chezmoi/private_Library/LaunchAgents/com.stavrobot.imcp-app.plist.tmpl`;
- the authoritative Stavrobot runbook at `~/STAVROBOT.md` and its managed
  chezmoi source copy at `~/.local/share/chezmoi/STAVROBOT.md`. Review these
  together during migration and archival; this repository task does not edit
  either home-directory runbook copy.

The existing bridge template may still point its Python and working-directory
paths at `~/Developer/stavrobot-imcp`. The replacement template must point at
`~/Developer/stavrobot-imcp-plugin`, or the operator must intentionally retire
the job. The app template and bridge template must be reconciled together so a
managed rendered file is not removed only to be recreated by chezmoi.

For a later approved migration, use this order without exposing credentials:

1. Inventory the old checkout, deployed bundle, both `launchctl` labels, the
   reserved tmux supervisor `stavrobot-imcp-bridge`, the two LaunchAgent chezmoi
   source entries, and both Stavrobot runbook copies (`~/STAVROBOT.md` and
   `~/.local/share/chezmoi/STAVROBOT.md`). Review targeted
   `chezmoi status`/`chezmoi diff` output and the rendered plist paths; leave
   unrelated managed state untouched. Treat the home runbook and its managed source copy
   as a separate documentation change, not as a reason to edit either one here.
2. Identify the one active bridge supervisor. Stop only the old supervisor,
   then boot out both `gui/$(id -u)/com.stavrobot.imcp` and
   `gui/$(id -u)/com.stavrobot.imcp-app` before changing or removing rendered
   files. Confirm that nothing still owns `127.0.0.1:8766`; do not kill an
   unrelated tmux session or listener.
3. Through the deliberate chezmoi workflow, update or retire the two managed
   LaunchAgent templates, render and lint both plists, and review the scoped
   diff. Apply only after the operator approves the path change. Do not use a
   direct deletion of a managed rendered file as reconciliation.
4. Install or copy the canonical root plugin bundle using the procedure above,
   preserve the installed configuration without copying it into source, and
   perform the controlled `plugin-runner` restart and ownership checks. Start
   exactly one new bridge supervisor and verify its paths, label, port, and
   authenticated read-only listing.
5. Before archival, verify that neither LaunchAgent nor any remaining process
   references `~/Developer/stavrobot-imcp`, consumers use the standalone
   plugin URL, the new bundle passes the plugin-runner checks, and the reviewed
   rollback bundle/host revision is retained. Recheck both `~/STAVROBOT.md` and
   `~/.local/share/chezmoi/STAVROBOT.md` for the canonical checkout and service
   paths, and reconcile them together through the separate chezmoi workflow if
   they differ. Only then archive the predecessor and remove its checkout if
   that separate change is approved.

Keep the predecessor branch/SHA in [`MAINTAINING.md`](MAINTAINING.md) as
provenance even after archival. If reconciliation fails, leave the old checkout
read-only and roll back to the last known-good reviewed deployment; do not
resume publishing from predecessor `main`.

## 5. Configure the plugin without exposing the token

Use Stavrobot's web settings or another trusted host-side secret/configuration
path. Do not paste `bridge_token` into an agent prompt or chat. The effective
configuration is equivalent to:

```json
{
  "bridge_url": "http://host.docker.internal:8766/bridge",
  "bridge_token": "<the protected host token>"
}
```

The URL must use `host.docker.internal` because the tool executes inside
`plugin-runner`; `127.0.0.1` and `localhost` there refer to the container, not
the macOS host. Keep the URL on the documented fixed bridge port `8766`.

### Plugin and agent permissions

After installation, use the Stavrobot web UI's plugin permissions control:

- Start with an explicit least-privilege list such as
  `["imcp_list_tools"]`.
- Add `"imcp_call"` only after the approved iMCP tools and first operation are
  known. The host bridge's own allowlist and the plugin permission list are
  separate layers.
- `[]` disables the plugin and `["*"]` permits every plugin tool; avoid `*`
  for a personal-data bridge unless that broad access has been explicitly
  approved.
- Grant the plugin only to the intended private/main agent through the
  agent-level allowed-plugin setting. **Exclude the iMCP plugin from every
  `telegram-group-*` agent.** Do not publish or rely on one machine-specific
  group-agent ID; inspect the actual agent IDs and each `allowed_plugins` value
  in the web UI before and after the change. Verify that every matching
  `telegram-group-*` agent remains excluded before testing any tool.

The `permissions` key is system-managed by Stavrobot's web UI; plugin tools do
not read it. Keep group routing and private-agent access as a separate review
from the host bridge's iMCP service selection, using the actual IDs and
`allowed_plugins` values shown by the web UI rather than display names alone.

## 6. Required reachability verification from `plugin-runner`

A host-only `curl` or a bridge process visible in tmux is not sufficient. The
following two checks must be run by an operator from the actual Stavrobot
`plugin-runner` container after its services are intentionally available.
These checks require an intentionally available deployment and are operator-run.

### 6.1 Check the host gateway and auth boundary

An unauthenticated GET should reach the bridge and return `401`; a connection
or DNS error is a failed gate:

```sh
cd /path/to/stavrobot
docker compose exec -T plugin-runner python3 - <<'PY'
import urllib.error
import urllib.request

request = urllib.request.Request(
    "http://host.docker.internal:8766/bridge",
    method="GET",
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        status = response.status
except urllib.error.HTTPError as error:
    status = error.code
if status != 401:
    raise SystemExit(f"expected 401 from the unauthenticated bridge check, got {status}")
print(
    "plugin-runner reached host.docker.internal:8766 "
    "(unauthenticated request rejected)"
)
PY
```

This check intentionally sends no credential. It confirms the required
container-to-host route and that the bridge has not silently removed auth. It
cannot trigger iMCP client approval: authentication is rejected before the
bridge opens an MCP session.

### 6.2 Check authenticated plugin traffic through the same route

With `bridge_url` and `bridge_token` configured in the installed plugin, first
confirm the actual bundle path inside the running `plugin-runner`. Do not
assume that a host checkout path is the mounted path, and do not inspect
`config.json`:

```sh
cd /path/to/stavrobot
BUNDLE_PATH="$(docker compose exec -T plugin-runner sh -c '
  set -eu
  for candidate in /plugins/*; do
    if [ -f "$candidate/manifest.json" ] &&
       grep -q \
         "\"name\"[[:space:]]*:[[:space:]]*\"imcp\"" \
         "$candidate/manifest.json"; then
      printf "%s" "$candidate"
      exit 0
    fi
  done
  exit 1
')" || {
  echo "iMCP plugin bundle was not found in /plugins" >&2
  exit 1
}
case "$BUNDLE_PATH" in
  /plugins/*) ;;
  *) echo "plugin bundle path was outside /plugins" >&2; exit 1 ;;
esac
printf 'bundle path: %s\n' "$BUNDLE_PATH"

docker compose exec -T plugin-runner sh -c \
  'id plug_imcp && stat -c "%U:%G %a %n" /plugins'
docker compose exec -T plugin-runner stat -c '%U:%G %a %n' \
  "$BUNDLE_PATH" "$BUNDLE_PATH/manifest.json"
```

The inspection must show the dedicated `plug_imcp` user and the bundle owned
by that user (the `/plugins` mount itself may have a different mount owner).
If it does not, stop and repair the controlled install/restart before running
a tool. A supported URL install still requires this check.

Now run the read-only listing smoke as `plug_imcp`, not root. The non-login
`sh -c` is intentional. The installed tool reads the token internally; no
token is placed in this command or its output:

```sh
docker compose exec -T -u plug_imcp \
  -w "$BUNDLE_PATH/imcp_list_tools" plugin-runner \
  sh -c 'printf "{}\n" | ./run.py' \
  | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if payload.get("ok") is not True:
    raise SystemExit("authenticated iMCP listing failed")
tools = payload.get("result", {}).get("tools")
if not isinstance(tools, list):
    raise SystemExit("authenticated iMCP listing returned no tool list")
print(f"authenticated plugin-runner bridge check passed ({len(tools)} tools listed)")
'
```

This is the required verification **from `plugin-runner` via
`host.docker.internal:8766`**. Do not substitute a host-only test. After it
passes, perform only the approved read-only smoke operation and confirm that
permissions still exclude every `telegram-group-*` agent.

If either check fails, keep the host bind at `127.0.0.1`. **Do not widen it to
`0.0.0.0` automatically if it fails.** Stop, inspect the bridge logs without
printing credentials, check host-gateway/DNS and local firewall behavior, and
review the container networking design with an operator. A wider bind would
make authenticated personal-data tools reachable from unintended interfaces.

## Login startup and crash recovery

Run from the repository after preparing the private token and allowlist. The
login-service prerequisite is the already-installed app bundle at
`/Applications/iMCP.app`; the installer only opens it and does not install or
copy iMCP:

```sh
./.venv/bin/python scripts/install_login_services.py
```

The installer validates configuration and port availability, renders the templates,
and loads two per-user LaunchAgents:

- `com.stavrobot.imcp-app` opens iMCP at GUI login. Quitting iMCP deliberately
  leaves it closed until it is reopened or the next login.
- `com.stavrobot.imcp` runs the bridge through a private-configuration preflight.
  `KeepAlive=true` restores it after an exit; `ThrottleInterval=30` bounds
  repeated restarts. Missing/invalid configuration or port conflicts fail with
  a generic diagnostic; no conflicting process is killed. Because `KeepAlive`
  remains enabled, a persistent preflight failure is retried every 30 seconds;
  use `launchctl bootout` to stop the retry loop and prevent continued log
  growth while repairing the configuration.

These services start after login, not before login or FileVault unlock. iMCP's
existing client trust and macOS permissions still apply. An app that has not
started yet is handled by the bridge's lazy connection on later requests.

The installer accepts matching rendered files and leaves already-active jobs
loaded; it refuses drift rather than overwriting an existing file. Stop an
existing tmux bridge explicitly before installation. To update installed login
services, boot out both labels and reconcile their rendered plists first:

```sh
launchctl bootout "gui/$(id -u)/com.stavrobot.imcp"
launchctl bootout "gui/$(id -u)/com.stavrobot.imcp-app"
```

Allow up to 18 seconds for the bridge's graceful `launchctl bootout` drain
before treating it as stuck. Do not force-kill the bridge or remove either
plist prematurely during that window. Use one bridge supervisor, never tmux
and launchd together.

Logs are in `~/Library/Logs/Stavrobot/imcp-bridge.{out,err}.log`. The launch job
uses umask 077. Treat logs as operational data and avoid publishing them.

Chezmoi may manage the two LaunchAgents using explicit `.plist.tmpl` source
names. The installer renders both templates with the home directory and checks
the resulting files before loading; if rendering manually, validate both with
`plutil -lint` first. Scope applies to those two files; do not apply unrelated
configuration drift. Keep the token and allowlist unmanaged. Runtime source
and its venv must remain available at `~/Developer/stavrobot-imcp-plugin`.

Check the authenticated connection with `./scripts/check_bridge.sh`. A
successful unauthenticated 401 establishes only HTTP reachability. A successful
authenticated listing establishes the iMCP session; actual tool access remains
controlled by the allowlist.

To stop automatic restarts, boot out the bridge job (killing its PID alone
causes launchd to restart it). Remove/disable both login jobs to undo startup:

```sh
launchctl bootout "gui/$(id -u)/com.stavrobot.imcp"
launchctl bootout "gui/$(id -u)/com.stavrobot.imcp-app"
```

Allow up to 18 seconds for the bridge's graceful `launchctl bootout` drain
before treating it as stuck. Do not force-kill the bridge or remove either
plist prematurely during that window.

Remove the corresponding managed LaunchAgent files only when uninstalling.
Keep private credentials unless intentionally removing or rotating them.

## Rollback and uninstall

Perform rollback in the reverse order, with explicit approval:

1. In the Stavrobot web UI, set the iMCP plugin permissions to `[]`, remove it
   from the intended agent, and remove the bridge URL/token from the installed
   plugin configuration. **Exclude it from every `telegram-group-*` agent.**
   Inspect the actual agent IDs and `allowed_plugins` values in the web UI to
   confirm no matching group agent retains access.
2. Stop only the supervisor that was used. For the manual helper, the reserved
   session is:

   ```sh
   tmux kill-session -t stavrobot-imcp-bridge
   ```

   For LaunchAgents, use the matching per-user `launchctl bootout` operation
   for both `com.stavrobot.imcp` and `com.stavrobot.imcp-app` before removing
   either rendered plist. This bootout is also required to stop a persistent
   preflight retry loop and its log growth. Do not kill an unrelated tmux
   session or listener.
3. Remove or quarantine only the deployed copy at
   `$STAVROBOT_ROOT/data/plugins/imcp/` after preserving any approved audit or
   configuration record. Do not remove the root plugin or host source files
   from this checkout as part of deployment rollback.
4. For chezmoi-managed LaunchAgents, review `chezmoi status` and
   `chezmoi diff`, then remove or reconcile the corresponding source entries
   through the deliberate chezmoi workflow before removing rendered files.
   Do not delete only a managed rendered file, since chezmoi will recreate it;
   leave unrelated managed state untouched.
5. After all clients are disabled and the active bridge supervisor has been
   stopped, remove the host token file using the operator's secure-storage
   policy, or rotate/revoke it if any copy may remain. Stopping first matters:
   a running bridge retains its in-memory credential, while deleting first
   leaves it live until exit and makes a `KeepAlive` LaunchAgent enter
   preflight retry. Do not print either the old or replacement token.
6. Optionally disable the selected iMCP services and revoke remembered client
   approval/macOS permissions manually. Leave unrelated existing plugins and
   their credentials untouched.

After rollback, verify that no process is listening on the fixed bridge port
and that every `telegram-group-*` agent's actual `allowed_plugins` value
excludes iMCP. Keep the source bundle and this runbook if a later re-deployment
is approved.

## Upgrading to iMCP 1.8.2+ (client credential)
iMCP 1.8.2 fixes security advisories GHSA-pfc6-qp66-c2ff and
GHSA-q4pc-f59f-9xmw and is the minimum supported version. Operator steps:
1. Stop the bridge supervisor (tmux session or LaunchAgent, see **Rollback and
   uninstall**), then update iMCP.app to 1.8.2 or newer and open it.
2. Start the bridge and run `./scripts/check_bridge.sh`. When iMCP shows the
   **Connection Request** for `stavrobot-imcp-bridge`, approve it and choose
   **Always trust this client**. iMCP then shows a client credential once.
3. Store it privately without echoing it. Remove any old file first (umask
   does not tighten an existing one), then paste at the silent prompt and press
   Return:
   ```sh
   rm -f "$HOME/.config/imcp-client.credential"
   ( umask 077; IFS= read -rs cred && printf '%s\n' "$cred" > "$HOME/.config/imcp-client.credential" )
   chmod 600 "$HOME/.config/imcp-client.credential"
   ```
   Never put it in chat, logs, shell history, the plist, or Git. Mode 0400 or
   0600 is accepted.
4. Restart the bridge. The start helper and `scripts/run_launchd_bridge.py`
   pass `--client-credential-file` only when that file exists (an existing file
   must be private); `scripts/probe_imcp.py` accepts the same option. The bridge
   pings a reused session before each request and relaunches `imcp-server` if it
   exited, without replaying a call.
5. Re-run `./scripts/check_bridge.sh`, then review the allowlist per §2.1.
Undo: stop the bridge, delete `~/.config/imcp-client.credential`, remove the
trusted client in iMCP's settings (revokes the credential), and restart; the
next connection will prompt for approval again. Reverting to an app older than
1.8.2 is unsupported.
## Stdio transport migration and rollback

This revision uses the supported bundled `imcp-server` stdio entrypoint from
iMCP **1.8.2 or newer**. The HTTP boundary remains
`127.0.0.1:8766/bridge`; the plugin URL, Bearer authentication, JSON operation
names, response envelope, allowlist, and no-LAN-exposure rule do not change.
There is no internal iMCP TCP endpoint to configure or expose.

If the selected app is older than 1.8.2, the bundled executable is missing or
not executable, or the stdio migration fails its read-only verification, stop
before invoking a tool. Do not copy individual transport files or reintroduce a
manually selected port into this revision.

### Roll back to the prior custom transport

To roll back the migration, perform a complete deployment rollback to the last
known-good repository revision (or release artifact) that contains the prior
custom TCP transport. That revision must be used with its own matching
requirements; do not mix the old transport with this revision's source or
virtual environment.

1. Disable the iMCP plugin in Stavrobot and stop the active tmux or LaunchAgent
   supervisor using the procedure in **Rollback and uninstall** above. Preserve
   the token, allowlist, and approved audit record unless they are separately
   being revoked.
2. Deploy the reviewed prior revision as a complete unit and install its pinned
   dependencies in a clean virtual environment. Keep the bridge bind, port,
   path, and auth settings at `127.0.0.1:8766/bridge`.
3. Start that bridge and resolve any manual iMCP permission or client-approval
   prompt. Run the host-side read-only `list_tools` check before re-enabling
   the plugin; a listing retry is safe, but do not replay a `call_tool` with an
   uncertain outcome.
4. Re-enable the plugin only after the authenticated listing succeeds from
   `plugin-runner`. Its `bridge_url` and HTTP request/response contract remain
   unchanged across this transport rollback.

When returning to stdio, stop the prior supervisor, deploy this revision with
an iMCP app at least 1.8.2, reinstall this revision's dependencies, and repeat
the executable, approval, reconnect, and plugin-runner checks. Never resolve a
failed container check by binding the bridge to `0.0.0.0`.
