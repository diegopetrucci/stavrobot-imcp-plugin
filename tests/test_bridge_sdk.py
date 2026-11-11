from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest
from mcp import ClientSession

from bridge.server import DEFAULT_RUNTIME_CLOSE_TIMEOUT, AsyncBridgeRuntime, BridgeService
from stavrobot_imcp.transport import open_imcp_session


class _FileEvent:
    def __init__(self, path: Path) -> None:
        self.path = path

    def set(self) -> None:
        self.path.touch()

    async def wait(self) -> None:
        while not self.path.exists():
            await asyncio.sleep(0.005)


class FixtureMCPServer:
    """Executable newline-delimited MCP fixture for the real SDK client."""

    def __init__(
        self,
        *,
        block_calls: bool = False,
        drop_calls: bool = False,
        withhold_initialize: bool = False,
        ignore_stdin_eof: bool = False,
    ) -> None:
        self.block_calls = block_calls
        self.drop_calls = drop_calls
        self.withhold_initialize = withhold_initialize
        self.ignore_stdin_eof = ignore_stdin_eof
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.server_path = self.root / "imcp-server"
        self._started_marker = self.root / "started"
        self._starts_file = self.root / "starts"
        self._closed_marker = self.root / "closed"
        self._pid_file = self.root / "pid"
        self._methods_file = self.root / "methods"
        self._calls_file = self.root / "calls"
        self._release_marker = self.root / "release"
        self.call_started = _FileEvent(self.root / "call-started")
        self.initialize_received = _FileEvent(self.root / "initialize")
        self.release_calls = _FileEvent(self._release_marker)
        self._write_server()

    def _write_server(self) -> None:
        script = f'''#!{sys.executable}
import json
import os
import pathlib
import signal
import sys
import time

root = pathlib.Path({str(self.root)!r})
started = root / "started"
closed = root / "closed"
methods = root / "methods"
calls = root / "calls"
release = root / "release"
pid_file = root / "pid"
started.touch()
with (root / "starts").open("a", encoding="utf-8") as starts_output:
    starts_output.write(str(os.getpid()) + "\\n")
pid_file.write_text(str(os.getpid()), encoding="utf-8")


def terminate(_signum, _frame):
    closed.touch()
    raise SystemExit(0)

if {self.ignore_stdin_eof!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, terminate)


def record(path, value):
    with path.open("a", encoding="utf-8") as output:
        output.write(value + "\\n")

def send(message):
    sys.stdout.write(json.dumps(message) + "\\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if not isinstance(method, str):
            continue
        record(methods, method)
        request_id = message.get("id")
        if request_id is None:
            continue
        if method == "initialize":
            (root / "initialize").touch()
            if {self.withhold_initialize!r}:
                continue
            result = {{
                "protocolVersion": "2025-11-25",
                "capabilities": {{}},
                "serverInfo": {{"name": "tlh-fixture", "version": "1"}},
            }}
        elif method == "tools/list":
            result = {{
                "tools": [{{
                    "name": "fixture_tool",
                    "description": "A stdio regression fixture",
                    "inputSchema": {{"type": "object"}},
                }}]
            }}
        elif method == "tools/call":
            params = message.get("params")
            arguments = params.get("arguments", {{}}) if isinstance(params, dict) else {{}}
            record(calls, json.dumps(arguments))
            (root / "call-started").touch()
            if {self.drop_calls!r}:
                return
            while {self.block_calls!r} and not release.exists():
                time.sleep(0.005)
            result = {{
                "content": [{{"type": "text", "text": "fixture-ok"}}],
                "isError": False,
            }}
        else:
            result = {{}}
        send({{"jsonrpc": "2.0", "id": request_id, "result": result}})
    if {self.ignore_stdin_eof!r}:
        while True:
            time.sleep(0.05)

try:
    main()
finally:
    if not {self.ignore_stdin_eof!r}:
        closed.touch()
'''
        self.server_path.write_text(script, encoding="utf-8")
        self.server_path.chmod(0o755)

    async def start(self) -> Path:
        return self.server_path

    @property
    def connection_count(self) -> int:
        if not self._starts_file.exists():
            return 0
        return len(self._starts_file.read_text(encoding="utf-8").splitlines())

    @property
    def pid(self) -> int | None:
        if not self._pid_file.exists():
            return None
        return int(self._pid_file.read_text(encoding="utf-8"))

    def pid_alive(self) -> bool:
        process_id = self.pid
        if process_id is None:
            return False
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @property
    def closed_count(self) -> int:
        return int(self._closed_marker.exists() or (self.connection_count and not self.pid_alive()))

    @property
    def connections(self) -> set[str]:
        return {"stdio"} if self.connection_count and not self.closed_count else set()

    @property
    def connection_tasks(self) -> set[str]:
        return self.connections

    @property
    def methods(self) -> list[str]:
        if not self._methods_file.exists():
            return []
        return self._methods_file.read_text(encoding="utf-8").splitlines()

    @property
    def call_arguments(self) -> list[dict[str, Any]]:
        if not self._calls_file.exists():
            return []
        return [json.loads(line) for line in self._calls_file.read_text(encoding="utf-8").splitlines()]

    async def wait_for_closed(self, count: int = 1, *, timeout: float = 1.0) -> None:
        async def wait() -> None:
            while self.closed_count < count or self.connections or self.connection_tasks:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait(), timeout)

    async def stop(self) -> None:
        self.release_calls.set()
        if self.connection_count and not self.closed_count:
            try:
                await self.wait_for_closed()
            except TimeoutError:
                process_id = self.pid
                if process_id is not None and self.pid_alive():
                    os.kill(process_id, 9)
                await self.wait_for_closed(timeout=1.0)
        self._temporary_directory.cleanup()


class ServerSequence:
    def __init__(self, server_paths: list[Path]) -> None:
        self.server_paths = list(server_paths)
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def __call__(self) -> Path:
        self.calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        if not self.server_paths:
            raise AssertionError("fixture server was launched more times than expected")
        if len(self.server_paths) > 1:
            return self.server_paths.pop(0)
        return self.server_paths[0]


def tracked_session_factory(
    server_paths: Callable[[], Awaitable[Path]],
    entered_tasks: list[asyncio.Task[Any] | None],
    exited_tasks: list[asyncio.Task[Any] | None],
) -> Callable[[], Any]:
    def factory() -> Any:
        @asynccontextmanager
        async def context() -> Any:
            async with open_imcp_session(
                server_path=await server_paths(),
                read_timeout_seconds=2.0,
                startup_timeout=2.0,
            ) as session:
                entered_tasks.append(asyncio.current_task())
                yield session
            exited_tasks.append(asyncio.current_task())

        return context()

    return factory


def make_service(
    server_paths: Callable[[], Awaitable[Path]],
    *,
    entered_tasks: list[asyncio.Task[Any] | None] | None = None,
    exited_tasks: list[asyncio.Task[Any] | None] | None = None,
    **kwargs: Any,
) -> BridgeService:
    entered = entered_tasks if entered_tasks is not None else []
    exited = exited_tasks if exited_tasks is not None else []
    return BridgeService(
        session_factory=tracked_session_factory(server_paths, entered, exited),
        call_timeout=kwargs.pop("call_timeout", 2.0),
        setup_timeout=kwargs.pop("setup_timeout", 2.0),
        **kwargs,
    )


async def close_fixture(*servers: FixtureMCPServer) -> None:
    for server in servers:
        await server.stop()


def install_loop_exception_capture() -> list[dict[str, Any]]:
    exceptions: list[dict[str, Any]] = []

    def exception_handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exceptions.append(context)

    asyncio.get_running_loop().set_exception_handler(exception_handler)
    return exceptions


def assert_no_pending_tasks() -> None:
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
    assert pending == [], [task.get_name() for task in pending]


def assert_owner_terminal(owner: Any, *, expected_cancelled: bool = False) -> None:
    task = owner.task
    assert task is not None and task.done()
    if expected_cancelled:
        assert task.cancelled()
    else:
        assert not task.cancelled()
        assert task.exception() is None
    assert owner.exit_error is None


@pytest.mark.filterwarnings("error")
def test_real_sdk_initialization_and_repeated_request_reuse() -> None:
    async def scenario() -> None:
        fixture = FixtureMCPServer()
        server_path = await fixture.start()
        server_paths = ServerSequence([server_path])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(server_paths, entered_tasks=entered, exited_tasks=exited)
        try:
            first = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 1}}
            )
            owner = service._session_owner
            assert owner is not None
            assert isinstance(service._session, ClientSession)
            second = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
            )

            assert first.payload["ok"] is True
            assert second.payload["ok"] is True
            assert server_paths.calls == 1
            assert fixture.connection_count == 1
            assert fixture.methods.count("initialize") == 1
            assert fixture.methods.count("tools/call") == 2
            assert fixture.call_arguments == [{"n": 1}, {"n": 2}]
            assert owner.task is not None
            assert not owner.task.done()

            await asyncio.create_task(service.close(), name="idle-service-close")
            await fixture.wait_for_closed()
            assert owner.task.done()
            assert owner.exit_error is None
            assert entered == exited
            assert entered[0] is owner.task
        finally:
            await close_fixture(fixture)

    asyncio.run(scenario())


def test_real_sdk_bridge_short_caller_wait_detaches_and_kills_stubborn_child() -> None:
    async def scenario() -> None:
        fixture = FixtureMCPServer(ignore_stdin_eof=True)
        server_path = await fixture.start()
        service = BridgeService(server_path=server_path)
        try:
            response = await asyncio.wait_for(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}}
                ),
                timeout=2.0,
            )
            assert response.payload["ok"] is True
            process_id = fixture.pid
            assert process_id is not None and fixture.pid_alive()

            # This caller wait is deliberately below the SDK's 6.5-second
            # escalation budget.  Bridge owner cleanup remains on the loop and
            # the caller detaches without cancelling stdio_client.__aexit__.
            await asyncio.wait_for(service.close(), timeout=0.25)
            await fixture.wait_for_closed(timeout=10.0)
            assert not fixture.pid_alive()
        finally:
            await close_fixture(fixture)

    asyncio.run(scenario())


def test_real_sdk_runtime_shutdown_with_concurrent_close_callers_retires_queued_calls_without_relaunch() -> None:
    async def scenario() -> None:
        fixture = FixtureMCPServer(block_calls=True, ignore_stdin_eof=True)
        server_path = await fixture.start()
        service = BridgeService(server_path=server_path)
        runtime = AsyncBridgeRuntime(service)
        try:
            runtime.start()
            first_future = asyncio.run_coroutine_threadsafe(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 1}}
                ),
                runtime.loop,
            )
            await asyncio.wait_for(fixture.call_started.wait(), timeout=2.0)
            second_future = asyncio.run_coroutine_threadsafe(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
                ),
                runtime.loop,
            )
            await asyncio.sleep(0.05)
            assert not second_future.done()

            close_tasks = [
                asyncio.create_task(asyncio.to_thread(runtime.close), name="runtime-close-1"),
                asyncio.create_task(asyncio.to_thread(runtime.close), name="runtime-close-2"),
            ]

            async def wait_for_closing() -> None:
                while not service._closing:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(wait_for_closing(), timeout=2.0)
            assert not second_future.done()
            fixture.release_calls.set()

            first_result = await asyncio.wait_for(asyncio.wrap_future(first_future), timeout=2.0)
            second_result = await asyncio.wait_for(asyncio.wrap_future(second_future), timeout=2.0)
            await asyncio.wait_for(asyncio.gather(*close_tasks), timeout=19.0)

            assert first_result.payload["ok"] is True
            assert second_result.payload["error"]["code"] == "mcp_unavailable"
            assert fixture.connection_count == 1
            await fixture.wait_for_closed(timeout=10.0)
            assert not fixture.pid_alive()
            assert runtime.loop.is_closed()
            assert not runtime._thread.is_alive()
        finally:
            if not runtime._closed:
                await asyncio.to_thread(runtime.close)
            await close_fixture(fixture)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["call_tool", "list_tools"])
def test_real_sdk_shutdown_during_stalled_cold_startup_skips_later_phases(operation: str) -> None:
    async def scenario() -> None:
        fixture = FixtureMCPServer(ignore_stdin_eof=True)
        server_path = await fixture.start()
        startup_started = threading.Event()

        @asynccontextmanager
        async def slow_context() -> Any:
            async with open_imcp_session(
                server_path=server_path,
                read_timeout_seconds=2.0,
                startup_timeout=2.0,
            ) as session:
                startup_started.set()
                await asyncio.Event().wait()
                yield session

        service = BridgeService(
            session_factory=lambda: slow_context(),
            call_timeout=2.0,
            setup_timeout=2.0,
        )
        runtime = AsyncBridgeRuntime(service)
        request = (
            {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 1}}
            if operation == "call_tool"
            else {"operation": "list_tools"}
        )
        try:
            runtime.start()
            first_future = asyncio.run_coroutine_threadsafe(service.execute(request), runtime.loop)
            await asyncio.wait_for(asyncio.to_thread(startup_started.wait, 2.0), timeout=3.0)
            owner = service._session_owner

            async def wait_for_child_pid() -> int:
                while fixture.pid is None:
                    await asyncio.sleep(0.005)
                return fixture.pid

            child_pid = await asyncio.wait_for(wait_for_child_pid(), timeout=1.0)
            assert owner is not None and owner.task is not None
            assert child_pid == fixture.pid and fixture.pid_alive()

            second_future = asyncio.run_coroutine_threadsafe(service.execute(request), runtime.loop)
            await asyncio.sleep(0.05)
            assert not second_future.done()

            close_started = time.monotonic()
            close_task = asyncio.create_task(asyncio.to_thread(runtime.close), name="stalled-cold-runtime-close")

            async def wait_for_closing() -> None:
                while not service._closing:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(wait_for_closing(), timeout=2.0)
            assert not second_future.done()
            await asyncio.wait_for(close_task, timeout=DEFAULT_RUNTIME_CLOSE_TIMEOUT)
            close_elapsed = time.monotonic() - close_started

            assert close_elapsed < DEFAULT_RUNTIME_CLOSE_TIMEOUT
            assert runtime.loop.is_closed()
            assert not runtime._thread.is_alive()
            assert first_future.done() and not first_future.cancelled()
            assert second_future.done() and not second_future.cancelled()
            first_result = await asyncio.wrap_future(first_future)
            second_result = await asyncio.wrap_future(second_future)
            assert first_result.status_code == 503
            assert first_result.payload["error"]["code"] == "mcp_unavailable"
            assert first_result.payload["error"]["app_reachable"] is False
            assert second_result.status_code == 503
            assert second_result.payload["error"]["code"] == "mcp_unavailable"
            assert second_result.payload["error"]["app_reachable"] is False
            methods = fixture.methods
            assert "initialize" not in methods
            assert "tools/list" not in methods
            assert "tools/call" not in methods
            assert fixture.connection_count == 1
            await fixture.wait_for_closed(timeout=10.0)
            assert not fixture.pid_alive()
            assert owner.task.cancelling() == 1
            assert_owner_terminal(owner, expected_cancelled=True)
            assert service._session_owner is None
        finally:
            if not runtime._closed:
                await asyncio.to_thread(runtime.close)
            await close_fixture(fixture)

    asyncio.run(scenario())


def test_real_sdk_reconnect_retirement_during_shutdown_does_not_launch_second_child() -> None:
    async def scenario() -> None:
        first_fixture = FixtureMCPServer()
        second_fixture = FixtureMCPServer()
        first_path = await first_fixture.start()
        second_path = await second_fixture.start()
        retirement_started = asyncio.Event()
        release_retirement = asyncio.Event()
        factory_calls = 0

        @asynccontextmanager
        async def first_context() -> Any:
            async with open_imcp_session(
                server_path=first_path,
                read_timeout_seconds=2.0,
                startup_timeout=2.0,
            ) as session:
                try:
                    yield session
                finally:
                    retirement_started.set()
                    await release_retirement.wait()

        def factory() -> Any:
            nonlocal factory_calls
            factory_calls += 1
            if factory_calls == 1:
                return first_context()
            if factory_calls == 2:
                return open_imcp_session(
                    server_path=second_path,
                    read_timeout_seconds=2.0,
                    startup_timeout=2.0,
                )
            raise AssertionError("fixture server was launched more times than expected")

        service = BridgeService(
            session_factory=factory,
            call_timeout=2.0,
            setup_timeout=2.0,
        )
        reconnect_task: asyncio.Task[Any] | None = None
        close_task: asyncio.Task[Any] | None = None
        try:
            first = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 1}}
            )
            assert first.payload["ok"] is True
            assert first_fixture.connection_count == 1

            # Leave the first owner in place while making the next request take
            # the reconnect retirement path.
            service._session_known_dead = True
            reconnect_task = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
                ),
                name="reconnect-during-shutdown",
            )
            await asyncio.wait_for(retirement_started.wait(), timeout=2.0)
            assert not reconnect_task.done()

            close_task = asyncio.create_task(service.close(), name="reconnect-shutdown")
            while not service._closing:
                await asyncio.sleep(0)
            assert not reconnect_task.done()
            release_retirement.set()

            second = await asyncio.wait_for(reconnect_task, timeout=10.0)
            await asyncio.wait_for(close_task, timeout=10.0)
            await first_fixture.wait_for_closed(timeout=10.0)

            assert second.status_code == 503
            assert second.payload["error"]["code"] == "mcp_unavailable"
            assert first_fixture.connection_count == 1
            assert second_fixture.connection_count == 0
            assert factory_calls == 2
            assert service._session_owner is None
        finally:
            release_retirement.set()
            if not service._closed:
                await service.close()
            await close_fixture(first_fixture, second_fixture)

    asyncio.run(scenario())


def test_real_sdk_disconnect_never_replays_and_reconnects_with_fresh_stdio_server() -> None:
    async def scenario() -> None:
        first_fixture = FixtureMCPServer(drop_calls=True)
        second_fixture = FixtureMCPServer()
        first_path = await first_fixture.start()
        second_path = await second_fixture.start()
        server_paths = ServerSequence([first_path, second_path])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(server_paths, entered_tasks=entered, exited_tasks=exited)
        try:
            first = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"value": "once"}}
            )
            assert first.payload["error"]["code"] == "unknown_outcome"
            assert first.payload["error"]["retryable"] is False
            await first_fixture.wait_for_closed()
            first_owner_task = entered[0]
            assert first_owner_task is not None and first_owner_task.done()
            assert len(first_fixture.call_arguments) == 1

            second = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"value": "later"}}
            )
            second_owner = service._session_owner
            assert second_owner is not None
            assert second.payload["ok"] is True
            assert second_owner.task is not first_owner_task
            assert server_paths.calls == 2
            assert len(first_fixture.call_arguments) == 1
            assert len(second_fixture.call_arguments) == 1
            assert second_fixture.call_arguments[0] == {"value": "later"}

            await service.close()
            await second_fixture.wait_for_closed()
            assert second_owner.task is not None and second_owner.task.done()
            assert second_owner.exit_error is None
            assert entered == exited
        finally:
            await close_fixture(first_fixture, second_fixture)

    asyncio.run(scenario())


@pytest.mark.parametrize("exit_phase", ["idle", "in_flight"])
def test_real_sdk_server_exit_on_imcp_disconnect_recovers_on_next_call(exit_phase: str) -> None:
    """imcp-server >= 1.8.2 exits when its iMCP connection ends instead of reconnecting."""

    async def scenario() -> None:
        first_fixture = FixtureMCPServer(block_calls=exit_phase == "in_flight")
        second_fixture = FixtureMCPServer()
        server_paths = ServerSequence([await first_fixture.start(), await second_fixture.start()])
        service = make_service(server_paths)
        try:
            if exit_phase == "idle":
                warmup = await service.execute({"operation": "list_tools"})
                assert warmup.payload["ok"] is True
                assert first_fixture.pid_alive()
                os.kill(first_fixture.pid, 9)
                await first_fixture.wait_for_closed()
                pending = None
            else:
                pending = asyncio.create_task(
                    service.execute(
                        {"operation": "call_tool", "name": "fixture_tool", "arguments": {"value": "once"}}
                    )
                )
                await first_fixture.call_started.wait()
                os.kill(first_fixture.pid, 9)

            if pending is not None:
                failed = await asyncio.wait_for(pending, 5.0)
                assert failed.payload["ok"] is False
                assert failed.payload["error"]["code"] == "unknown_outcome"
                assert failed.payload["error"]["retryable"] is False
                await first_fixture.wait_for_closed()
                assert len(first_fixture.call_arguments) == 1

            second = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"value": "later"}}
            )
            assert second.payload["ok"] is True
            assert server_paths.calls == 2
            assert second_fixture.connection_count == 1
            assert second_fixture.call_arguments == [{"value": "later"}]
            assert len(first_fixture.call_arguments) == (1 if pending is not None else 0)

            await service.close()
            await second_fixture.wait_for_closed()
        finally:
            await close_fixture(first_fixture, second_fixture)

    asyncio.run(scenario())


def test_real_sdk_initialize_cancellation_closes_owner_and_reconnects() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        first_fixture = FixtureMCPServer(withhold_initialize=True)
        second_fixture = FixtureMCPServer()
        first_path = await first_fixture.start()
        second_path = await second_fixture.start()
        server_paths = ServerSequence([first_path, second_path])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(server_paths, entered_tasks=entered, exited_tasks=exited)
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}},
                ),
                name="initialize-cancel-request",
            )
            await asyncio.wait_for(first_fixture.initialize_received.wait(), timeout=2.0)
            owner = service._session_owner
            assert owner is not None and owner.task is not None
            assert entered == [owner.task]
            fixture_tasks = set(first_fixture.connection_tasks)
            background_tasks = [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
                and task is not request
                and task is not owner.task
                and task not in fixture_tasks
            ]
            assert background_tasks

            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            await first_fixture.wait_for_closed()
            await asyncio.sleep(0)

            assert_owner_terminal(owner)
            assert entered == exited == [owner.task]
            assert first_fixture.connection_count == 1
            assert first_fixture.methods == ["initialize"]
            assert first_fixture.connections == set()
            assert first_fixture.connection_tasks == set()
            for task in background_tasks:
                assert task.done()
                if not task.cancelled():
                    assert task.exception() is None
            assert_no_pending_tasks()
            assert loop_exceptions == []

            later = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
            )
            second_owner = service._session_owner
            assert second_owner is not None and second_owner.task is not None
            assert second_owner.task is not owner.task
            assert later.payload["ok"] is True
            assert server_paths.calls == 2
            assert first_fixture.call_arguments == []
            assert second_fixture.call_arguments == [{"n": 2}]

            await service.close()
            await second_fixture.wait_for_closed()
            assert_owner_terminal(second_owner)
            assert entered == exited
            assert entered[1] is second_owner.task
            await asyncio.sleep(0)
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(first_fixture, second_fixture)

    asyncio.run(scenario())


def test_real_sdk_readiness_cancellation_race_retires_owner_without_replay() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        first_fixture = FixtureMCPServer()
        second_fixture = FixtureMCPServer()
        first_path = await first_fixture.start()
        second_path = await second_fixture.start()
        server_start_requested = asyncio.Event()
        release_server_start = asyncio.Event()
        server_start_calls = 0

        async def server_path_provider() -> Path:
            nonlocal server_start_calls
            server_start_calls += 1
            if server_start_calls == 1:
                server_start_requested.set()
                await release_server_start.wait()
                return first_path
            if server_start_calls == 2:
                return second_path
            raise AssertionError("fixture server was launched more times than expected")

        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(server_path_provider, entered_tasks=entered, exited_tasks=exited)
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}},
                ),
                name="readiness-race-request",
            )
            await asyncio.wait_for(server_start_requested.wait(), timeout=2.0)
            owner = service._session_owner
            assert owner is not None and owner.task is not None
            cancellation_callback_ran = asyncio.Event()

            def cancel_after_ready(_ready: asyncio.Future[Any]) -> None:
                assert owner.ready.done()
                cancellation_callback_ran.set()
                request.cancel()

            owner.ready.add_done_callback(cancel_after_ready)
            release_server_start.set()
            await asyncio.wait_for(cancellation_callback_ran.wait(), timeout=2.0)
            with pytest.raises(asyncio.CancelledError):
                await request
            await first_fixture.wait_for_closed()
            await asyncio.sleep(0)

            assert_owner_terminal(owner)
            assert entered == exited == [owner.task]
            assert first_fixture.call_arguments == []
            assert first_fixture.connections == set()
            assert first_fixture.connection_tasks == set()

            later = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
            )
            second_owner = service._session_owner
            assert second_owner is not None and second_owner.task is not None
            assert second_owner.task is not owner.task
            assert later.payload["ok"] is True
            assert server_start_calls == 2
            assert second_fixture.call_arguments == [{"n": 2}]
            await service.close()
            await second_fixture.wait_for_closed()
            assert_owner_terminal(second_owner)
            assert entered == exited
            assert entered[1] is second_owner.task
            await asyncio.sleep(0)
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(first_fixture, second_fixture)

    asyncio.run(scenario())


def test_real_sdk_setup_cancellation_retires_owner_without_task_cancellation() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        fixture = FixtureMCPServer()
        server_path = await fixture.start()
        server_paths = ServerSequence([server_path])
        server_paths.block = True
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(
            server_paths,
            entered_tasks=entered,
            exited_tasks=exited,
            setup_timeout=1.0,
        )
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}},
                ),
                name="setup-request",
            )
            await asyncio.wait_for(server_paths.started.wait(), timeout=2.0)
            owner = service._session_owner
            assert owner is not None and owner.task is not None
            request.cancel()
            server_paths.release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            await fixture.wait_for_closed(timeout=10.0)
            await asyncio.sleep(0)

            assert_owner_terminal(owner)
            assert entered == exited == [owner.task]
            assert service._session_owner is None
            assert fixture.connection_count == 1
            assert fixture.connections == set()
            assert fixture.connection_tasks == set()
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(fixture)

    asyncio.run(scenario())


def test_real_sdk_inflight_cancellation_closes_owner_and_later_request_reconnects() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        first_fixture = FixtureMCPServer(block_calls=True)
        second_fixture = FixtureMCPServer()
        first_path = await first_fixture.start()
        second_path = await second_fixture.start()
        server_paths = ServerSequence([first_path, second_path])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(server_paths, entered_tasks=entered, exited_tasks=exited)
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 1}},
                ),
                name="inflight-request",
            )
            await asyncio.wait_for(first_fixture.call_started.wait(), timeout=2.0)
            owner = service._session_owner
            assert owner is not None and owner.task is not None
            assert entered == [owner.task]
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            first_fixture.release_calls.set()
            await first_fixture.wait_for_closed()
            await asyncio.sleep(0)
            assert_owner_terminal(owner)
            assert entered == exited == [owner.task]
            assert first_fixture.connections == set()
            assert first_fixture.connection_tasks == set()
            assert len(first_fixture.call_arguments) == 1
            assert_no_pending_tasks()
            assert loop_exceptions == []

            later = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
            )
            second_owner = service._session_owner
            assert second_owner is not None and second_owner.task is not None
            assert later.payload["ok"] is True
            assert server_paths.calls == 2
            assert len(first_fixture.call_arguments) == 1
            assert second_fixture.call_arguments == [{"n": 2}]
            await service.close()
            await second_fixture.wait_for_closed()
            assert_owner_terminal(second_owner)
            assert entered == exited
            assert entered[1] is second_owner.task
            await asyncio.sleep(0)
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(first_fixture, second_fixture)

    asyncio.run(scenario())


def test_real_sdk_idle_and_inflight_shutdown_finish_with_no_owner_leak() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        idle_fixture = FixtureMCPServer()
        idle_path = await idle_fixture.start()
        idle_entered: list[asyncio.Task[Any] | None] = []
        idle_exited: list[asyncio.Task[Any] | None] = []
        idle_service = make_service(
            ServerSequence([idle_path]),
            entered_tasks=idle_entered,
            exited_tasks=idle_exited,
        )
        try:
            idle_result = await idle_service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {}}
            )
            assert idle_result.payload["ok"] is True
            idle_owner = idle_service._session_owner
            assert idle_owner is not None and idle_owner.task is not None
            assert idle_entered == [idle_owner.task]
            await asyncio.wait_for(idle_service.close(), timeout=0.5)
            await idle_fixture.wait_for_closed()
            await asyncio.sleep(0)
            assert_owner_terminal(idle_owner)
            assert idle_entered == idle_exited == [idle_owner.task]
            assert idle_fixture.connections == set()
            assert idle_fixture.connection_tasks == set()
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(idle_fixture)

        active_fixture = FixtureMCPServer(block_calls=True)
        active_path = await active_fixture.start()
        active_entered: list[asyncio.Task[Any] | None] = []
        active_exited: list[asyncio.Task[Any] | None] = []
        active_service = make_service(
            ServerSequence([active_path]),
            entered_tasks=active_entered,
            exited_tasks=active_exited,
        )
        try:
            request = asyncio.create_task(
                active_service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}},
                ),
                name="shutdown-inflight-request",
            )
            await asyncio.wait_for(active_fixture.call_started.wait(), timeout=2.0)
            active_owner = active_service._session_owner
            assert active_owner is not None and active_owner.task is not None
            assert active_entered == [active_owner.task]
            close_task = asyncio.create_task(active_service.close(), name="inflight-service-close")
            await asyncio.sleep(0)
            assert not close_task.done()
            active_fixture.release_calls.set()
            result = await asyncio.wait_for(request, timeout=0.5)
            await asyncio.wait_for(close_task, timeout=0.5)
            assert result.payload["ok"] is True
            await active_fixture.wait_for_closed()
            await asyncio.sleep(0)
            assert_owner_terminal(active_owner)
            assert active_entered == active_exited == [active_owner.task]
            assert active_fixture.connections == set()
            assert active_fixture.connection_tasks == set()
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(active_fixture)

    asyncio.run(scenario())