from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp import types

from scripts import probe_imcp


class _FakeSession:
    def __init__(self) -> None:
        self.initialize_calls = 0
        self.list_params: list[types.PaginatedRequestParams | None] = []
        self.call_tool_called = False
        self._pages = [
            types.ListToolsResult(
                tools=[
                    types.Tool(
                        name="first",
                        description="First tool",
                        inputSchema={"type": "object"},
                        title="must not be captured",
                    )
                ],
                nextCursor="next",
            ),
            types.ListToolsResult(
                tools=[
                    types.Tool(
                        name="second",
                        description=None,
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
            ),
        ]

    async def initialize(self) -> None:
        self.initialize_calls += 1

    async def list_tools(
        self,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        self.list_params.append(params)
        return self._pages[len(self.list_params) - 1]

    async def call_tool(self, *_args: object, **_kwargs: object) -> None:
        self.call_tool_called = True
        raise AssertionError("probe must not invoke an MCP tool")


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.client_info: types.Implementation | None = None

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        return None


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_pagination_cursor_fails_closed(self) -> None:
        fake_session = _FakeSession()
        fake_session._pages = [
            types.ListToolsResult(tools=[], nextCursor="repeat"),
            types.ListToolsResult(tools=[], nextCursor="repeat"),
        ]

        with patch.object(
            probe_imcp,
            "open_imcp_session",
            return_value=_FakeSessionContext(fake_session),
        ):
            with self.assertRaisesRegex(RuntimeError, "repeated tools/list cursor"):
                await probe_imcp._list_all_tools()

    async def test_lists_tools_through_shared_session_without_calling_tools(self) -> None:
        fake_session = _FakeSession()
        fake_context = _FakeSessionContext(fake_session)

        with patch.object(
            probe_imcp,
            "open_imcp_session",
            return_value=fake_context,
        ) as open_session:
            metadata = await probe_imcp._list_all_tools()

        self.assertEqual(fake_session.initialize_calls, 1)
        self.assertEqual(
            fake_session.list_params,
            [None, types.PaginatedRequestParams(cursor="next")],
        )
        open_session.assert_called_once()
        self.assertEqual(
            open_session.call_args.kwargs["server_path"],
            probe_imcp.APP_PATH / "Contents" / "MacOS" / "imcp-server",
        )
        client_info = open_session.call_args.kwargs["client_info"]
        self.assertEqual(client_info.name, "imcp-tools-probe")
        self.assertEqual(client_info.version, probe_imcp.CLIENT_VERSION)
        self.assertFalse(fake_session.call_tool_called)
        self.assertEqual(
            metadata,
            [
                {
                    "name": "first",
                    "description": "First tool",
                    "inputSchema": {"type": "object"},
                },
                {
                    "name": "second",
                    "description": None,
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ],
        )

    async def test_lists_tools_from_custom_app_bundle(self) -> None:
        fake_session = _FakeSession()
        custom_app = Path("/alternate/iMCP.app")

        with patch.object(
            probe_imcp,
            "open_imcp_session",
            return_value=_FakeSessionContext(fake_session),
        ) as open_session:
            await probe_imcp._list_all_tools(custom_app)

        open_session.assert_called_once()
        self.assertEqual(
            open_session.call_args.kwargs["server_path"],
            custom_app / "Contents" / "MacOS" / "imcp-server",
        )

    async def test_run_forwards_custom_app_to_tool_listing(self) -> None:
        custom_app = Path("/alternate/iMCP.app")

        with tempfile.TemporaryDirectory() as temporary_directory:
            args = argparse.Namespace(
                app=custom_app,
                output=Path(temporary_directory) / "metadata.md",
                app_version="1.4.1",
                capture_date="2026-09-07",
                timeout=1.0,
                client_credential_file=None,
            )
            with (
                patch.object(probe_imcp, "_launch_app_if_needed") as launch_app,
                patch.object(
                    probe_imcp,
                    "_list_all_tools",
                    new_callable=AsyncMock,
                    return_value=[],
                ) as list_all_tools,
            ):
                await probe_imcp._run(args)

        launch_app.assert_called_once_with(custom_app)
        list_all_tools.assert_awaited_once_with(custom_app, None)

    async def test_credential_file_is_loaded_and_passed_to_session(self) -> None:
        fake_context = _FakeSessionContext(_FakeSession())
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "cred"
            credential.write_text("probe-secret\n", encoding="utf-8")
            credential.chmod(0o600)
            with patch.object(probe_imcp, "open_imcp_session", return_value=fake_context) as open_session:
                await probe_imcp._list_all_tools(client_credential_file=credential)
            self.assertEqual(open_session.call_args.kwargs["client_credential"], "probe-secret")

            credential.chmod(0o644)
            with self.assertRaises(ValueError) as caught:
                await probe_imcp._list_all_tools(client_credential_file=credential)
            self.assertNotIn("probe-secret", str(caught.exception))

    def test_missing_app_is_a_friendly_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            args = argparse.Namespace(
                app=Path(temporary_directory) / "iMCP.app",
                output=Path(temporary_directory) / "metadata.md",
                app_version="1.4.1",
                capture_date="2026-09-07",
                timeout=1.0,
            )
            stderr = io.StringIO()
            with (
                patch.object(probe_imcp, "_parse_args", return_value=args),
                patch.object(probe_imcp, "_is_imcp_running", return_value=False),
                contextlib.redirect_stderr(stderr),
            ):
                result = probe_imcp.main()

        self.assertEqual(result, 1)
        self.assertIn("probe failed: iMCP app not found:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_open_failure_is_a_friendly_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path = Path(temporary_directory) / "iMCP.app"
            app_path.mkdir()
            args = argparse.Namespace(
                app=app_path,
                output=Path(temporary_directory) / "metadata.md",
                app_version="1.4.1",
                capture_date="2026-09-07",
                timeout=1.0,
            )
            stderr = io.StringIO()
            with (
                patch.object(probe_imcp, "_parse_args", return_value=args),
                patch.object(probe_imcp, "_is_imcp_running", return_value=False),
                patch.object(
                    probe_imcp.subprocess,
                    "run",
                    side_effect=subprocess.CalledProcessError(1, ["open"]),
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = probe_imcp.main()

        self.assertEqual(result, 1)
        self.assertIn("probe failed: could not open iMCP app:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_transport_failure_is_a_friendly_failure(self) -> None:
        args = argparse.Namespace(
            app=Path("/unused/iMCP.app"),
            output=Path("/unused/metadata.md"),
            app_version="1.4.1",
            capture_date="2026-09-07",
            timeout=1.0,
            client_credential_file=None,
        )

        async def fail_listing(_app_path: Path, _credential_file: Path | None) -> list[dict[str, object]]:
            raise RuntimeError("transport unavailable")

        stderr = io.StringIO()
        with (
            patch.object(probe_imcp, "_parse_args", return_value=args),
            patch.object(probe_imcp, "_launch_app_if_needed"),
            patch.object(probe_imcp, "_list_all_tools", fail_listing),
            contextlib.redirect_stderr(stderr),
        ):
            result = probe_imcp.main()

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "probe failed: transport unavailable\n")
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_interrupts_are_not_converted_to_probe_failures(self) -> None:
        args = argparse.Namespace(
            app=Path("/unused/iMCP.app"),
            output=Path("/unused/metadata.md"),
            app_version="1.4.1",
            capture_date="2026-09-07",
            timeout=1.0,
        )
        for interrupt in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt):
                with (
                    patch.object(probe_imcp, "_parse_args", return_value=args),
                    patch.object(probe_imcp, "_run", new=lambda _args: object()),
                    patch.object(probe_imcp.asyncio, "run", side_effect=interrupt),
                ):
                    with self.assertRaises(interrupt):
                        probe_imcp.main()

    def test_render_document_contains_only_allowed_tool_metadata(self) -> None:
        rendered = probe_imcp._render_document(
            [
                {
                    "name": "first",
                    "description": "First tool",
                    "inputSchema": {"type": "object"},
                }
            ],
            app_version="1.4.1",
            capture_date="2026-09-06",
        )

        payload = rendered.split("```json\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(
            json.loads(payload),
            [
                {
                    "name": "first",
                    "description": "First tool",
                    "inputSchema": {"type": "object"},
                }
            ],
        )
        self.assertIn("iMCP **1.4.1**", rendered)
        self.assertIn("**2026-09-06**", rendered)
        self.assertIn(
            "The generic full iMCP 1.4.1 tool surface when all services are enabled "
            "is documented below; this is not a record of the operator's Mac configuration.",
            rendered,
        )
        self.assertIn("Supported deployments require iMCP **>=1.8.2**", rendered)
        self.assertIn("bundled `imcp-server` over stdio", rendered)
        self.assertIn("no tool is invoked", rendered)


if __name__ == "__main__":
    unittest.main()
