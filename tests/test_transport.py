from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp import MCPError, types
from mcp.client import stdio as sdk_stdio

from stavrobot_imcp import transport


def _write_executable(directory: Path, body: str) -> Path:
    path = directory / "imcp-server"
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


SERVER_BODY = r'''
import json
import pathlib
import sys

marker = pathlib.Path(__MARKER__)

def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()

try:
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            continue
        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stdio-fixture", "version": "1"},
                },
            })
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": [{"name": "fixture", "inputSchema": {"type": "object"}}]},
            })
finally:
    marker.write_text("closed", encoding="utf-8")
'''


IGNORANT_SERVER_BODY = r'''
import os
import pathlib
import signal
import time

pid_file = pathlib.Path(__PID_FILE__)
pid_file.write_text(str(os.getpid()), encoding="utf-8")
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    time.sleep(0.05)
'''


class _FakeClientSession:
    def __init__(self, read_stream: object, write_stream: object, **kwargs: object) -> None:
        self.streams = (read_stream, write_stream)
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeClientSession:
        return self

    async def __aexit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        return None


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def test_shutdown_floor_matches_pinned_sdk_escalation_budget(self) -> None:
        sdk_budget = (
            sdk_stdio._WRITER_FLUSH_TIMEOUT
            + sdk_stdio.PROCESS_TERMINATION_TIMEOUT
            + sdk_stdio.FORCE_KILL_TIMEOUT
            + sdk_stdio._KILL_REAP_TIMEOUT
        )
        self.assertAlmostEqual(sdk_budget, 6.5)
        self.assertAlmostEqual(transport.SDK_SHUTDOWN_BUDGET, sdk_budget)
        self.assertAlmostEqual(transport.MIN_SHUTDOWN_TIMEOUT, 7.0)
        self.assertGreaterEqual(transport.MIN_SHUTDOWN_TIMEOUT, sdk_budget)

    def test_default_command_path_is_the_bundled_executable(self) -> None:
        self.assertEqual(
            transport.DEFAULT_SERVER_PATH,
            Path("/Applications/iMCP.app/Contents/MacOS/imcp-server"),
        )

    def test_path_validation_rejects_relative_directory_and_non_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(transport.TransportConfigurationError):
                transport._validate_server_path(Path("imcp-server"))
            with self.assertRaises(transport.TransportConfigurationError):
                transport._validate_server_path(root)

            non_executable = root / "not-executable"
            non_executable.write_text("#!/bin/sh\n", encoding="utf-8")
            non_executable.chmod(0o600)
            with self.assertRaises(PermissionError):
                transport._validate_server_path(non_executable)

    def test_missing_command_fails_before_sdk_launch(self) -> None:
        missing = Path(tempfile.gettempdir()) / "imcp-server-does-not-exist-for-test"
        with self.assertRaises(FileNotFoundError):
            transport._server_parameters(missing)

    async def test_short_shutdown_timeout_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write_executable(Path(directory), "")
            with self.assertRaisesRegex(transport.TransportConfigurationError, "at least"):
                async with transport.open_imcp_session(server_path=path, shutdown_timeout=0.25):
                    pass

    async def test_command_construction_uses_official_sdk_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write_executable(Path(directory), "")
            captured: list[object] = []
            captured_errlogs: list[object] = []

            @asynccontextmanager
            async def fake_stdio(server: object, *, errlog: object) -> object:
                captured.append(server)
                captured_errlogs.append(errlog)
                yield (object(), object())

            client_info = types.Implementation(name="transport-test", version="1")
            with (
                patch.object(transport, "stdio_client", fake_stdio),
                patch.object(transport, "ClientSession", _FakeClientSession),
            ):
                async with transport.open_imcp_session(
                    server_path=path,
                    client_info=client_info,
                    read_timeout_seconds=0.2,
                    startup_timeout=0.2,
                ) as session:
                    self.assertIsInstance(session, _FakeClientSession)

            self.assertEqual(len(captured), 1)
            self.assertEqual(len(captured_errlogs), 1)
            self.assertEqual(getattr(captured_errlogs[0], "name", None), os.devnull)
            self.assertTrue(getattr(captured_errlogs[0], "closed", False))
            parameters = captured[0]
            assert isinstance(parameters, transport.StdioServerParameters)
            self.assertEqual(parameters.command, str(path))
            self.assertEqual(parameters.args, [])
            self.assertEqual(parameters.env, None)
            self.assertEqual(session.kwargs["client_info"], client_info)
            self.assertEqual(session.kwargs["read_timeout_seconds"], 0.2)

    async def test_startup_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write_executable(Path(directory), "")

            @asynccontextmanager
            async def slow_stdio(_server: object, *, errlog: object) -> object:
                await asyncio.sleep(1)
                yield (object(), object())

            started = time.monotonic()
            with (
                patch.object(transport, "stdio_client", slow_stdio),
                self.assertRaisesRegex(TimeoutError, "stdio startup"),
            ):
                async with transport.open_imcp_session(
                    server_path=path,
                    startup_timeout=0.02,
                ):
                    pass
            self.assertLess(time.monotonic() - started, 0.5)

    async def test_real_sdk_stdio_lifecycle_initializes_and_lists_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "closed"
            body = SERVER_BODY.replace("__MARKER__", repr(str(marker)))
            path = _write_executable(root, body)
            client_info = types.Implementation(name="transport-test", version="1")

            async with transport.open_imcp_session(
                server_path=path,
                client_info=client_info,
                read_timeout_seconds=1.0,
                startup_timeout=1.0,
            ) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()

            self.assertEqual(initialized.server_info.name, "stdio-fixture")
            self.assertEqual([tool.name for tool in tools.tools], ["fixture"])
            self.assertTrue(marker.exists())

    async def test_default_shutdown_kills_process_ignoring_stdin_eof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "pid"
            body = IGNORANT_SERVER_BODY.replace("__PID_FILE__", repr(str(pid_file)))
            path = _write_executable(root, body)

            async with transport.open_imcp_session(server_path=path):
                for _ in range(100):
                    if pid_file.exists():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(pid_file.exists())
            pid = int(pid_file.read_text(encoding="utf-8"))

            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                still_running = False
            except PermissionError:
                still_running = True
            else:
                still_running = True
            self.assertFalse(still_running)

    async def test_read_timeout_is_enforced_by_official_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = r'''
import sys
for line in sys.stdin:
    # Deliberately keep initialize unanswered so ClientSession's read bound fires.
    if line:
        sys.stdout.flush()
'''
            path = _write_executable(Path(directory), body)

            async with transport.open_imcp_session(
                server_path=path,
                read_timeout_seconds=0.02,
                startup_timeout=0.5,
            ) as session:
                with pytest.raises(MCPError) as raised:
                    await session.initialize()
                self.assertEqual(raised.value.code, types.REQUEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main()


class ClientCredentialTests(unittest.TestCase):
    SECRET = "s3cret-credential-value"

    def _file(self, directory: str, mode: int, contents: str | None = None) -> Path:
        path = Path(directory) / "cred"
        path.write_text(self.SECRET + "\n" if contents is None else contents, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_env_only_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write_executable(Path(directory), "")
            self.assertIsNone(transport._server_parameters(path).env)
            env = transport._server_parameters(path, self.SECRET).env
            assert env is not None
            self.assertEqual(env["IMCP_CLIENT_CREDENTIAL"], self.SECRET)
            for key, value in transport.get_default_environment().items():
                self.assertEqual(env[key], value)

    def test_loader_accepts_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._file(directory, 0o600)
            self.assertEqual(transport.load_client_credential(path), self.SECRET)
            path.chmod(0o400)
            self.assertEqual(transport.load_client_credential(path), self.SECRET)

    def test_loader_rejects_bad_files_without_leaking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases = [
                self._file(directory, 0o644),
                self._file(directory, 0o660),
                self._file(directory, 0o600, "   \n"),
                self._file(directory, 0o600, f"{self.SECRET} extra"),
                Path(directory) / "missing",
            ]
            for path in cases:
                with self.assertRaises(transport.TransportConfigurationError) as caught:
                    transport.load_client_credential(path)
                self.assertNotIn(self.SECRET, str(caught.exception))
            link = Path(directory) / "link"
            link.symlink_to(self._file(directory, 0o600))
            with self.assertRaises(transport.TransportConfigurationError):
                transport.load_client_credential(link)
