#!/usr/bin/env python3
"""Validate private configuration, then replace this process with the bridge."""

import os
from pathlib import Path
import socket
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bridge.server import load_allowlist, load_token


def preflight(home: Path) -> tuple[Path, Path]:
    token = home / ".config/imcp-bridge.token"
    allowlist = home / ".config/imcp-bridge-tools.json"
    for path in (token, allowlist):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("configuration must be an owned regular file")
        if stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
            raise ValueError("configuration must be mode 0400 or 0600")
    load_token(token)
    load_allowlist(allowlist)
    with socket.socket() as sock:
        # Match HTTPServer's reuse policy: recently closed connections in
        # TIME_WAIT must not look like a live listener after a crash.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 8766))
    return token, allowlist


def main() -> int:
    try:
        token, allowlist = preflight(Path.home())
    except Exception:
        print("bridge preflight failed: check private configuration and port 8766; launchd will retry after its throttle interval", file=sys.stderr)
        return 78
    os.execv(sys.executable, [sys.executable, str(ROOT / "bridge/server.py"),
        "--bind", "127.0.0.1", "--port", "8766", "--path", "/bridge",
        "--token-file", str(token), "--allowlist-file", str(allowlist),
        "--call-timeout", "10"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
