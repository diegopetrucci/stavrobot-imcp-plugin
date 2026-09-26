from __future__ import annotations

import argparse
import contextlib
import io
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    @staticmethod
    def _write_info_plist(app_path: Path, metadata: object) -> None:
        info_plist = app_path / "Contents" / "Info.plist"
        info_plist.parent.mkdir(parents=True, exist_ok=True)
        info_plist.write_bytes(plistlib.dumps(metadata))

    @classmethod
    def _make_app(
        cls,
        root: Path,
        *,
        version: str = "1.6.0",
        executable_name: str = "iMCP",
    ) -> tuple[Path, Path]:
        app_path = root / "iMCP.app"
        executable = app_path / "Contents" / "MacOS" / executable_name
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fake executable")
        cls._write_info_plist(
            app_path,
            {
                "CFBundleExecutable": executable_name,
                "CFBundleShortVersionString": version,
            },
        )
        return app_path, executable

    @staticmethod
    def _running_process(
        pid: int,
        executable: Path,
        *,
        device: int | None = None,
        inode: int | None = None,
    ) -> probe_imcp._RunningProcess:
        identity = probe_imcp._file_identity(executable, label="test")
        return probe_imcp._RunningProcess(
            pid=pid,
            executable=probe_imcp._ExecutableIdentity(
                path=identity.path,
                device=identity.device if device is None else device,
                inode=identity.inode if inode is None else inode,
            ),
        )

    def test_reads_selected_app_version_from_info_plist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path = Path(temporary_directory) / "iMCP.app"
            self._write_info_plist(
                app_path,
                {"CFBundleShortVersionString": "1.6.0"},
            )

            self.assertEqual(probe_imcp._read_app_version(app_path), "1.6.0")

    def test_missing_or_invalid_app_version_metadata_fails_clearly(self) -> None:
        cases = (
            ("missing", None),
            ("missing key", {}),
            ("invalid value", {"CFBundleShortVersionString": 1.6}),
        )
        for label, metadata in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    app_path = Path(temporary_directory) / "iMCP.app"
                    if metadata is not None:
                        self._write_info_plist(app_path, metadata)

                    with self.assertRaisesRegex(
                        RuntimeError,
                        "CFBundleShortVersionString",
                    ):
                        probe_imcp._read_app_version(app_path)

    def test_malformed_xml_app_version_metadata_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path = Path(temporary_directory) / "iMCP.app"
            info_plist = app_path / "Contents" / "Info.plist"
            info_plist.parent.mkdir(parents=True)
            info_plist.write_bytes(
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<plist version="1.0"><dict>'
            )

            with self.assertRaisesRegex(
                RuntimeError,
                r"invalid iMCP Info\.plist; cannot read "
                r"CFBundleShortVersionString",
            ):
                probe_imcp._read_app_version(app_path)

    def test_lsof_parser_selects_main_executable_from_multiple_text_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _app_path, executable = self._make_app(root)
            unrelated = root / "unrelated.dylib"
            unrelated.write_bytes(b"unrelated file")
            locale_file = root / "LC_COLLATE"
            locale_file.write_bytes(b"locale file")
            dyld_file = root / "dyld"
            dyld_file.write_bytes(b"dyld file")
            identity = probe_imcp._file_identity(executable, label="test")
            unrelated_identity = probe_imcp._file_identity(unrelated, label="test")
            locale_identity = probe_imcp._file_identity(locale_file, label="test")
            dyld_identity = probe_imcp._file_identity(dyld_file, label="test")
            lsof_output = (
                "p42\n"
                "f3\n"
                "tREG\n"
                f"D{unrelated_identity.device:#x}\n"
                f"i{unrelated_identity.inode}\n"
                f"n{unrelated_identity.path}\n"
                "ftxt\n"
                "tREG\n"
                f"D{identity.device:#x}\n"
                f"i{identity.inode}\n"
                f"n{identity.path}\n"
                "ftxt\n"
                "tREG\n"
                f"D{locale_identity.device:#x}\n"
                f"i{locale_identity.inode}\n"
                f"n{locale_identity.path}\n"
                "ftxt\n"
                "tREG\n"
                f"D{dyld_identity.device:#x}\n"
                f"i{dyld_identity.inode}\n"
                f"n{dyld_identity.path}\n"
                "f4\n"
                "tCHR\n"
                "D0x1\n"
                "i2\n"
                "n/dev/null\n"
            )
            completed = subprocess.CompletedProcess(
                args=[probe_imcp.LSOF_PATH],
                returncode=0,
                stdout=lsof_output,
                stderr="",
            )
            with patch.object(
                probe_imcp.subprocess,
                "run",
                return_value=completed,
            ) as run:
                observed = probe_imcp._read_running_executable(42)

            self.assertEqual(observed, identity)
            run.assert_called_once_with(
                [
                    probe_imcp.LSOF_PATH,
                    "-nP",
                    "-a",
                    "-p",
                    "42",
                    "-d",
                    "txt",
                    "-F",
                    "ftDin",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=probe_imcp.PROCESS_QUERY_TIMEOUT,
            )

    def test_process_probe_uses_absolute_pgrep_path_and_timeout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[probe_imcp.PGREP_PATH],
            returncode=1,
            stdout="",
            stderr="",
        )
        with patch.object(
            probe_imcp.subprocess,
            "run",
            return_value=completed,
        ) as run:
            self.assertFalse(probe_imcp._is_imcp_running())

        run.assert_called_once_with(
            [probe_imcp.PGREP_PATH, "-x", "iMCP"],
            capture_output=True,
            text=True,
            check=False,
            timeout=probe_imcp.PROCESS_QUERY_TIMEOUT,
        )

    def test_missing_running_identity_fails_closed(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["lsof"],
            returncode=0,
            stdout="ftxt\nn/Applications/iMCP.app/Contents/MacOS/iMCP\n",
            stderr="",
        )
        with patch.object(probe_imcp.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                RuntimeError,
                "could not establish running iMCP executable identity for pid 42",
            ):
                probe_imcp._read_running_executable(42)

    def test_running_process_from_different_app_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            selected_app, _selected_executable = self._make_app(root / "selected")
            _other_app, other_executable = self._make_app(root / "other")
            process = self._running_process(42, other_executable)

            with (
                patch.object(probe_imcp, "_is_imcp_running", return_value=True),
                patch.object(
                    probe_imcp,
                    "_inspect_running_imcp",
                    return_value=(process,),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "running iMCP executable does not match selected app",
                ):
                    probe_imcp._launch_app_if_needed(selected_app)

    def test_stale_same_path_executable_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            selected_app, selected_executable = self._make_app(Path(temporary_directory))
            identity = probe_imcp._file_identity(selected_executable, label="test")
            stale_process = self._running_process(
                42,
                selected_executable,
                inode=identity.inode + 1,
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "running iMCP executable does not match selected app",
            ):
                probe_imcp._require_selected_app_process(
                    selected_app,
                    processes=(stale_process,),
                )

    def test_cold_launch_polls_until_process_provenance_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path, executable = self._make_app(Path(temporary_directory))
            process = self._running_process(42, executable)
            not_ready = RuntimeError(
                "iMCP is not running from the selected app executable"
            )
            with (
                patch.object(probe_imcp, "_is_imcp_running", return_value=False),
                patch.object(
                    probe_imcp.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=[probe_imcp.OPEN_PATH],
                        returncode=0,
                    ),
                ) as open_app,
                patch.object(
                    probe_imcp,
                    "_require_selected_app_process",
                    side_effect=[not_ready, process],
                ) as require_process,
                patch.object(probe_imcp.time, "sleep") as sleep,
            ):
                observed = probe_imcp._launch_app_if_needed(app_path)

            self.assertEqual(observed, process)
            self.assertEqual(require_process.call_count, 2)
            sleep.assert_called_once_with(probe_imcp.LAUNCH_PROVENANCE_INTERVAL)
            open_app.assert_called_once_with(
                [probe_imcp.OPEN_PATH, str(app_path)],
                check=True,
                timeout=probe_imcp.PROCESS_QUERY_TIMEOUT,
            )

    def test_cold_launch_provenance_polling_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path, _executable = self._make_app(Path(temporary_directory))
            not_ready = RuntimeError(
                "iMCP is not running from the selected app executable"
            )
            with (
                patch.object(probe_imcp, "_is_imcp_running", return_value=False),
                patch.object(
                    probe_imcp.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=[probe_imcp.OPEN_PATH],
                        returncode=0,
                    ),
                ),
                patch.object(
                    probe_imcp,
                    "_require_selected_app_process",
                    side_effect=not_ready,
                ) as require_process,
                patch.object(probe_imcp.time, "sleep") as sleep,
                patch.object(probe_imcp, "LAUNCH_PROVENANCE_ATTEMPTS", 3),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "did not become the selected app process after launch",
                ):
                    probe_imcp._launch_app_if_needed(app_path)

            self.assertEqual(require_process.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_capture_rejects_pid_change_after_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path, executable = self._make_app(Path(temporary_directory))
            before = self._running_process(42, executable)
            after = self._running_process(43, executable)

            with patch.object(
                probe_imcp,
                "_inspect_running_imcp",
                return_value=(after,),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "iMCP process changed during metadata capture",
                ):
                    probe_imcp._verify_capture_process(app_path, before)

    async def test_capture_does_not_write_after_process_provenance_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app_path, executable = self._make_app(root)
            output = root / "metadata.md"
            args = argparse.Namespace(
                app=app_path,
                output=output,
                app_version=None,
                capture_date="2026-09-07",
                timeout=1.0,
            )
            before = self._running_process(42, executable)

            async def list_tools() -> list[dict[str, object]]:
                return []

            with (
                patch.object(
                    probe_imcp,
                    "_launch_app_if_needed",
                    return_value=before,
                ),
                patch.object(
                    probe_imcp,
                    "_verify_capture_process",
                    side_effect=RuntimeError(
                        "running iMCP executable does not match selected app"
                    ),
                ),
                patch.object(probe_imcp, "_list_all_tools", list_tools),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "running iMCP executable does not match selected app",
                ):
                    await probe_imcp._run(args)

            self.assertFalse(output.exists())

    async def test_default_capture_uses_selected_app_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app_path = Path(temporary_directory) / "iMCP.app"
            self._write_info_plist(
                app_path,
                {"CFBundleShortVersionString": "1.6.0"},
            )
            output = Path(temporary_directory) / "metadata.md"
            args = argparse.Namespace(
                app=app_path,
                output=output,
                app_version=None,
                capture_date="2026-09-07",
                timeout=1.0,
            )

            async def list_tools() -> list[dict[str, object]]:
                return []

            with (
                patch.object(
                    probe_imcp,
                    "_launch_app_if_needed",
                    return_value=object(),
                ),
                patch.object(probe_imcp, "_verify_capture_process"),
                patch.object(probe_imcp, "_list_all_tools", list_tools),
            ):
                await probe_imcp._run(args)

            self.assertIn("iMCP **1.6.0**", output.read_text(encoding="utf-8"))

    async def test_explicit_app_version_override_skips_metadata_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            args = argparse.Namespace(
                app=Path(temporary_directory) / "missing-iMCP.app",
                output=Path(temporary_directory) / "metadata.md",
                app_version="manual-version",
                capture_date="2026-09-07",
                timeout=1.0,
            )

            async def list_tools() -> list[dict[str, object]]:
                return []

            with (
                patch.object(
                    probe_imcp,
                    "_read_app_version",
                    side_effect=AssertionError("override must skip metadata lookup"),
                ),
                patch.object(
                    probe_imcp,
                    "_launch_app_if_needed",
                    return_value=object(),
                ),
                patch.object(probe_imcp, "_verify_capture_process"),
                patch.object(probe_imcp, "_list_all_tools", list_tools),
            ):
                await probe_imcp._run(args)

            self.assertIn(
                "iMCP **manual-version**",
                args.output.read_text(encoding="utf-8"),
            )

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
                    side_effect=subprocess.CalledProcessError(
                        1,
                        [probe_imcp.OPEN_PATH],
                    ),
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
        )

        async def fail_listing() -> list[dict[str, object]]:
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
        self.assertIn(
            "If the live bridge allowlist uses `*`, this surface can grow when iMCP adds a\n"
            "tool without any allowlist edit.",
            rendered,
        )
        self.assertIn("No tool was invoked", rendered)

    def test_checked_in_metadata_matches_renderer_byte_for_byte(self) -> None:
        document = (Path(__file__).resolve().parents[1] / "docs/imcp-tools.md").read_text(
            encoding="utf-8",
        )
        payload = document.split("```json\n", 1)[1].split("\n```", 1)[0]

        self.assertEqual(
            probe_imcp._render_document(
                json.loads(payload),
                app_version="1.6.0",
                capture_date="2026-09-26",
            ),
            document,
        )


if __name__ == "__main__":
    unittest.main()
