#!/usr/bin/env python3
"""Install per-user login services without changing tokens or permissions."""

from __future__ import annotations

import http.client
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_launchd_bridge import preflight


LABELS = ("com.stavrobot.imcp-app", "com.stavrobot.imcp")
BRIDGE_LABEL = "com.stavrobot.imcp"
HOME_MARKER = "{{ .chezmoi.homeDir }}"
APP_PATH = Path("/Applications/iMCP.app")


class _LaunchctlFailure(RuntimeError):
    """A launchctl operation failed without retaining its diagnostic text."""


class _TemplateDrift(RuntimeError):
    """A rendered LaunchAgent path changed while installation was preparing."""


def _render_value(value: object, home: Path) -> object:
    if isinstance(value, str):
        return value.replace(HOME_MARKER, str(home))
    if isinstance(value, list):
        return [_render_value(item, home) for item in value]
    if isinstance(value, dict):
        return {
            _render_value(key, home): _render_value(item, home)
            for key, item in value.items()
        }
    return value


def render_plist(template: Path, home: Path) -> bytes:
    """Parse and render one plist template for a supplied home directory."""

    document = plistlib.loads(template.read_bytes())
    rendered = plistlib.dumps(_render_value(document, home))
    if b"{{" in rendered or b"}}" in rendered:
        raise ValueError("rendered plist contains unresolved template markers")
    # Keep the output contract explicit: callers receive a parseable plist.
    plistlib.loads(rendered)
    return rendered


def _render_templates(home: Path) -> dict[str, bytes]:
    return {
        label: render_plist(ROOT / f"{label}.plist", home)
        for label in LABELS
    }


def _run_launchctl(arguments: list[str], *, check: bool = False) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(arguments, capture_output=True, check=check)
    except Exception as exc:
        # Do not expose launchctl's stderr or exception details to the operator.
        raise _LaunchctlFailure from exc
    if check and result.returncode != 0:
        raise _LaunchctlFailure
    return result


def _job_is_loaded(domain: str, label: str) -> bool:
    result = _run_launchctl(["launchctl", "print", f"{domain}/{label}"])
    return result.returncode == 0


def _bootstrap(domain: str, target: Path) -> None:
    _run_launchctl(
        ["launchctl", "bootstrap", domain, str(target)],
        check=True,
    )


def _target_matches(target: Path, expected: bytes) -> bool:
    if target.is_symlink():
        return False
    if not target.exists():
        return True
    if not target.is_file():
        return False
    # Compare plist documents rather than plistlib's serialized bytes.  A
    # safely owned regular file may use a different valid plist encoding or
    # formatting while still representing the same LaunchAgent.
    existing = target.read_bytes()
    try:
        return plistlib.loads(existing) == plistlib.loads(expected)
    except Exception:
        # Invalid plist data, including parser-specific XML errors, is drift.
        return False


def _check_existing_targets(targets: dict[str, Path], rendered: dict[str, bytes]) -> bool:
    for label in LABELS:
        target = targets[label]
        try:
            matches = _target_matches(target, rendered[label])
        except OSError:
            print(
                "Could not inspect existing LaunchAgent files; no changes were made.",
                file=sys.stderr,
            )
            return False
        if not matches:
            print(
                "Existing launch template differs; reconcile it before installation.",
                file=sys.stderr,
            )
            return False
    return True


def _write_missing_targets(targets: dict[str, Path], rendered: dict[str, bytes]) -> None:
    for label in LABELS:
        target = targets[label]
        if target.is_symlink():
            raise _TemplateDrift
        if target.exists():
            if not _target_matches(target, rendered[label]):
                raise _TemplateDrift
            continue
        target.write_bytes(rendered[label])


def _prepare_targets(
    destination: Path,
    logs: Path,
    targets: dict[str, Path],
    rendered: dict[str, bytes],
) -> None:
    previous_umask = os.umask(0o077)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_missing_targets(targets, rendered)
    finally:
        os.umask(previous_umask)


def main() -> int:
    home = Path.home()
    domain = f"gui/{os.getuid()}"
    destination = home / "Library/LaunchAgents"
    logs = home / "Library/Logs/Stavrobot"
    targets = {
        label: destination / f"{label}.plist"
        for label in LABELS
    }

    try:
        rendered = _render_templates(home)
    except Exception:
        print(
            "Installation template validation failed; no changes were made.",
            file=sys.stderr,
        )
        return 1

    # Check every rendered file before inspecting or changing either job.  A
    # drifted second file must not leave the first job written or bootstrapped.
    if not _check_existing_targets(targets, rendered):
        return 1

    try:
        active = {
            label: _job_is_loaded(domain, label)
            for label in LABELS
        }
    except _LaunchctlFailure:
        print(
            "Could not inspect login services; no changes were made.",
            file=sys.stderr,
        )
        return 1

    try:
        if not APP_PATH.is_dir():
            raise ValueError("iMCP app is unavailable")
        # An active bridge already owns the fixed port.  Leave it alone and
        # keep installation idempotent instead of probing its live socket.
        if not active[BRIDGE_LABEL]:
            preflight(home)
    except Exception:
        print(
            "Installation preflight failed: check app, private configuration, and port 8766.",
            file=sys.stderr,
        )
        return 1

    try:
        _prepare_targets(destination, logs, targets, rendered)
    except _TemplateDrift:
        print(
            "Existing launch template differs; reconcile it before installation.",
            file=sys.stderr,
        )
        return 1
    except OSError:
        print(
            "Could not prepare LaunchAgent files; no service was bootstrapped.",
            file=sys.stderr,
        )
        return 1

    loaded: list[str] = []
    try:
        for label in LABELS:
            if active[label]:
                loaded.append(label)
                continue
            _bootstrap(domain, targets[label])
            loaded.append(label)
    except _LaunchctlFailure:
        print(
            "Login service bootstrap failed; no existing jobs were stopped or replaced.",
            file=sys.stderr,
        )
        if loaded:
            print(
                "Possible partial activation: "
                f"{', '.join(loaded)} may already be loaded; no rollback was attempted.",
                file=sys.stderr,
            )
        return 1

    for _ in range(30):
        connection = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", 8766, timeout=1)
            connection.request("GET", "/bridge")
            response = connection.getresponse()
            code = response.status
            if code == 401:
                print("Login services installed; bridge is listening and rejects unauthenticated requests.")
                return 0
        except (OSError, http.client.HTTPException):
            pass
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    # Readiness is best-effort; never leak a close diagnostic.
                    pass
        time.sleep(1)
    print("Services installed, but bridge readiness timed out; inspect launchctl status.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
