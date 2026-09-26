#!/usr/bin/env python3
"""Capture iMCP's read-only MCP tool metadata.

This probe initializes an MCP client over iMCP's shared Bonjour/loopback
transport and requests only ``tools/list``. It never calls an MCP tool, and
writes only each tool's name, description, and input schema to the output
document.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import plistlib
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError

# Keep direct execution (``python scripts/probe_imcp.py``) working without
# installing this repository as a package.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp import types

from stavrobot_imcp import open_imcp_session


APP_PATH = Path("/Applications/iMCP.app")
OPEN_PATH = "/usr/bin/open"
PGREP_PATH = "/usr/bin/pgrep"
LSOF_PATH = "/usr/sbin/lsof"
PROCESS_QUERY_TIMEOUT = 5.0
LAUNCH_PROVENANCE_ATTEMPTS = 30
LAUNCH_PROVENANCE_INTERVAL = 1.0
CLIENT_NAME = "imcp-tools-probe"
CLIENT_VERSION = "1.0.0"
DEFAULT_TIMEOUT = 300.0


def _repo_root() -> Path:
    return REPO_ROOT


@dataclass(frozen=True)
class _ExecutableIdentity:
    """Canonical executable path and the identity of the file it names."""

    path: Path
    device: int
    inode: int


@dataclass(frozen=True)
class _RunningProcess:
    """The executable identity observed for one running iMCP process."""

    pid: int
    executable: _ExecutableIdentity


def _running_imcp_pids() -> tuple[int, ...]:
    """Return iMCP PIDs, failing closed if the process list is unreadable."""

    try:
        result = subprocess.run(
            [PGREP_PATH, "-x", "iMCP"],
            capture_output=True,
            text=True,
            check=False,
            timeout=PROCESS_QUERY_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("could not inspect running iMCP processes") from exc
    if result.returncode == 1:
        return ()
    if result.returncode != 0:
        raise RuntimeError("could not inspect running iMCP processes")

    pids: list[int] = []
    for line in result.stdout.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            pid = int(value, 10)
        except ValueError as exc:
            raise RuntimeError("could not inspect running iMCP processes") from exc
        if pid <= 0:
            raise RuntimeError("could not inspect running iMCP processes")
        pids.append(pid)
    if not pids:
        raise RuntimeError("could not inspect running iMCP processes")
    return tuple(dict.fromkeys(pids))


def _is_imcp_running() -> bool:
    return bool(_running_imcp_pids())


def _read_app_info(app_path: Path) -> dict[str, Any]:
    """Read the selected app's Info.plist as a validated dictionary."""

    info_plist = app_path / "Contents" / "Info.plist"
    try:
        with info_plist.open("rb") as plist_file:
            metadata = plistlib.load(plist_file)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "iMCP Info.plist not found; cannot read "
            f"CFBundleShortVersionString: {info_plist}"
        ) from exc
    except (
        OSError,
        ExpatError,
        plistlib.InvalidFileException,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "invalid iMCP Info.plist; cannot read "
            f"CFBundleShortVersionString: {info_plist}"
        ) from exc

    if not isinstance(metadata, dict):
        raise RuntimeError(
            "invalid iMCP Info.plist; expected "
            f"CFBundleShortVersionString: {info_plist}"
        )
    return metadata


def _read_app_version(app_path: Path) -> str:
    """Read the selected app's short version from its Info.plist."""

    info_plist = app_path / "Contents" / "Info.plist"
    metadata = _read_app_info(app_path)
    version = metadata.get("CFBundleShortVersionString")
    if not isinstance(version, str) or not version or version != version.strip():
        raise RuntimeError(
            "invalid CFBundleShortVersionString in iMCP Info.plist: "
            f"{info_plist}"
        )
    return version


def _selected_app_executable(app_path: Path) -> Path:
    """Resolve the executable named by the selected app bundle."""

    info_plist = app_path / "Contents" / "Info.plist"
    executable = _read_app_info(app_path).get("CFBundleExecutable")
    if (
        not isinstance(executable, str)
        or not executable
        or executable != executable.strip()
        or Path(executable).name != executable
    ):
        raise RuntimeError(
            "invalid iMCP Info.plist; cannot read CFBundleExecutable: "
            f"{info_plist}"
        )
    return app_path / "Contents" / "MacOS" / executable


def _file_identity(path: Path, *, label: str) -> _ExecutableIdentity:
    """Return a canonical regular-file path and its filesystem identity."""

    try:
        canonical = path.resolve(strict=True)
        metadata = os.stat(canonical)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"could not establish {label} executable identity: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"could not establish {label} executable identity: {path}")
    return _ExecutableIdentity(
        path=canonical,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _parse_lsof_integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        try:
            return int(value, 16)
        except ValueError as exc:
            raise RuntimeError("could not establish running iMCP executable identity") from exc


def _read_running_executable(pid: int) -> _ExecutableIdentity:
    """Read one process's executable path and device/inode using macOS lsof."""

    try:
        result = subprocess.run(
            [LSOF_PATH, "-nP", "-a", "-p", str(pid), "-d", "txt", "-F", "ftDin"],
            capture_output=True,
            text=True,
            check=False,
            timeout=PROCESS_QUERY_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"could not establish running iMCP executable identity for pid {pid}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"could not establish running iMCP executable identity for pid {pid}"
        )

    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "f":
            if record.get("f") == "txt":
                records.append(record)
            record = {}
        record[field] = value
    if record.get("f") == "txt":
        records.append(record)

    executable_record = next(
        (record for record in records if record.get("f") == "txt"),
        None,
    )
    if executable_record is None:
        raise RuntimeError(
            f"could not establish running iMCP executable identity for pid {pid}"
        )

    raw_path = executable_record.get("n")
    raw_device = executable_record.get("D")
    raw_inode = executable_record.get("i")
    if raw_path is None or raw_device is None or raw_inode is None:
        raise RuntimeError(
            f"could not establish running iMCP executable identity for pid {pid}"
        )
    try:
        executable = _file_identity(
            Path(raw_path),
            label=f"running iMCP pid {pid}",
        )
        device = _parse_lsof_integer(raw_device)
        inode = _parse_lsof_integer(raw_inode)
    except RuntimeError as exc:
        raise RuntimeError(
            f"could not establish running iMCP executable identity for pid {pid}"
        ) from exc
    return _ExecutableIdentity(
        path=executable.path,
        device=device,
        inode=inode,
    )


def _inspect_running_imcp() -> tuple[_RunningProcess, ...]:
    return tuple(
        _RunningProcess(pid=pid, executable=_read_running_executable(pid))
        for pid in _running_imcp_pids()
    )


def _require_selected_app_process(
    app_path: Path,
    *,
    expected: _ExecutableIdentity | None = None,
    processes: tuple[_RunningProcess, ...] | None = None,
) -> _RunningProcess:
    selected = expected or _file_identity(
        _selected_app_executable(app_path),
        label="selected iMCP",
    )
    observed = _inspect_running_imcp() if processes is None else processes
    if not observed:
        raise RuntimeError(
            "iMCP is not running from the selected app executable: "
            f"{selected.path}"
        )
    if len(observed) != 1:
        raise RuntimeError(
            "could not establish a unique running iMCP process for selected app"
        )
    process = observed[0]
    if process.executable != selected:
        raise RuntimeError(
            "running iMCP executable does not match selected app: "
            f"expected {selected.path} (device {selected.device}, inode {selected.inode}), "
            f"found {process.executable.path} "
            f"(device {process.executable.device}, inode {process.executable.inode})"
        )
    return process


def _launch_app_if_needed(app_path: Path) -> _RunningProcess:
    if not app_path.is_dir():
        raise RuntimeError(f"iMCP app not found: {app_path}")

    # Never open a second app or silently replace a running process. A running
    # process from another bundle (including a stale Sparkle-updated process)
    # must be diagnosed by the operator and fails closed.
    if _is_imcp_running():
        return _require_selected_app_process(app_path)

    try:
        subprocess.run(
            [OPEN_PATH, str(app_path)],
            check=True,
            timeout=PROCESS_QUERY_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not open iMCP app: {app_path}") from exc

    # ``open`` returns before a menu-bar app necessarily has a process or a
    # readable executable record. Poll for provenance, but never wait forever
    # or accept a process that does not match the selected app.
    last_error: RuntimeError | None = None
    for attempt in range(LAUNCH_PROVENANCE_ATTEMPTS):
        try:
            return _require_selected_app_process(app_path)
        except RuntimeError as exc:
            last_error = exc
            if attempt + 1 < LAUNCH_PROVENANCE_ATTEMPTS:
                time.sleep(LAUNCH_PROVENANCE_INTERVAL)

    if last_error is None:
        raise RuntimeError("iMCP launch provenance polling was not configured")
    raise RuntimeError(
        "iMCP did not become the selected app process after launch: "
        f"{last_error}"
    ) from last_error


def _verify_capture_process(app_path: Path, before: _RunningProcess) -> None:
    """Require the same PID and executable identity after tools/list."""

    selected = _file_identity(
        _selected_app_executable(app_path),
        label="selected iMCP",
    )
    after = _require_selected_app_process(app_path, expected=selected)
    if after.pid != before.pid:
        raise RuntimeError(
            "iMCP process changed during metadata capture: "
            f"expected pid {before.pid}, found pid {after.pid}"
        )
    if after.executable != before.executable:
        raise RuntimeError(
            "iMCP executable identity changed during metadata capture"
        )


def _metadata_for_tool(tool: types.Tool) -> dict[str, Any]:
    """Keep only the fields explicitly allowed in the capture."""

    return {
        "name": tool.name,
        "description": tool.description,
        # MCP SDK model fields use snake_case attributes while retaining the
        # protocol's inputSchema alias on the wire.
        "inputSchema": tool.input_schema,
    }


async def _list_all_tools() -> list[dict[str, Any]]:
    async with open_imcp_session(
        client_info=types.Implementation(
            name=CLIENT_NAME,
            version=CLIENT_VERSION,
        ),
    ) as session:
        await session.initialize()

        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params = (
                types.PaginatedRequestParams(cursor=cursor)
                if cursor is not None
                else None
            )
            page = await session.list_tools(params=params)
            tools.extend(_metadata_for_tool(tool) for tool in page.tools)

            # SDK model fields use snake_case attributes for protocol aliases.
            cursor = page.next_cursor
            if cursor is None:
                return tools
            if cursor in seen_cursors:
                raise RuntimeError("iMCP returned a repeated tools/list cursor")
            seen_cursors.add(cursor)


def _render_document(
    tools: list[dict[str, Any]],
    *,
    app_version: str,
    capture_date: str,
) -> str:
    payload = json.dumps(tools, indent=2, ensure_ascii=False, sort_keys=False)
    return f"""# iMCP tools

Captured from iMCP **{app_version}** on **{capture_date}** using a read-only MCP handshake and `tools/list`.

The generic full iMCP {app_version} tool surface when all services are enabled is documented below; this is not a record of the operator's Mac configuration.

If the live bridge allowlist uses `*`, this surface can grow when iMCP adds a
tool without any allowlist edit. Treat every upgrade as requiring a fresh
`tools/list` review and explicit approval of the expanded read/write surface;
this document does not alter the live allowlist.

Only tool names, descriptions, and input schemas are recorded below. No tool was invoked and no tool result or personal data was captured.

```json
{payload}
```
"""


def _parse_args() -> argparse.Namespace:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app",
        type=Path,
        default=APP_PATH,
        help="path to iMCP.app, launched if iMCP is not running",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "docs/imcp-tools.md",
        help="metadata document to write",
    )
    parser.add_argument(
        "--app-version",
        default=None,
        help=(
            "iMCP version to record (defaults to "
            "CFBundleShortVersionString in the app's Info.plist)"
        ),
    )
    parser.add_argument(
        "--capture-date",
        default=date.today().isoformat(),
        help="ISO capture date to record (defaults to today)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="seconds to wait for handshake and tools/list",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    before = _launch_app_if_needed(args.app)
    app_version = (
        args.app_version
        if args.app_version is not None
        else _read_app_version(args.app)
    )

    try:
        tools = await asyncio.wait_for(
            _list_all_tools(),
            timeout=args.timeout,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            "timed out during the read-only MCP handshake/tools/list; "
            "check iMCP's manual client approval prompt"
        ) from exc

    _verify_capture_process(args.app, before)
    if args.app_version is None:
        final_app_version = _read_app_version(args.app)
        if final_app_version != app_version:
            raise RuntimeError(
                "selected iMCP app version changed during metadata capture: "
                f"started at {app_version}, ended at {final_app_version}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        _render_document(
            tools,
            app_version=app_version,
            capture_date=args.capture_date,
        ),
        encoding="utf-8",
    )
    print(f"Wrote read-only iMCP tool metadata to {args.output}", file=sys.stderr)


def _friendly_error(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    return detail or type(exc).__name__


def main() -> int:
    args = _parse_args()
    try:
        asyncio.run(_run(args))
    except Exception as exc:
        # Exception deliberately excludes KeyboardInterrupt and SystemExit.
        print(f"probe failed: {_friendly_error(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
