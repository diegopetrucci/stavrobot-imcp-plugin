from __future__ import annotations

import asyncio
import json
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import pytest
from mcp import ClientSession

from bridge.server import BridgeService
from stavrobot_imcp.transport import open_imcp_session


class FixtureMCPServer:
    """Small newline-delimited MCP fixture for the real SDK client."""

    def __init__(
        self,
        *,
        block_calls: bool = False,
        drop_calls: bool = False,
        withhold_initialize: bool = False,
    ) -> None:
        self.block_calls = block_calls
        self.drop_calls = drop_calls
        self.withhold_initialize = withhold_initialize
        self.server: asyncio.AbstractServer | None = None
        self.connections: set[asyncio.StreamWriter] = set()
        self.connection_tasks: set[asyncio.Task[Any]] = set()
        self.connection_count = 0
        self.closed_count = 0
        self.methods: list[str] = []
        self.call_arguments: list[dict[str, Any]] = []
        self.call_started = asyncio.Event()
        self.initialize_received = asyncio.Event()
        self.release_calls = asyncio.Event()
        self._closed_change = asyncio.Event()
        self.handler_errors: list[BaseException] = []

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        assert self.server.sockets
        return int(self.server.sockets[0].getsockname()[1])

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self.connection_tasks.add(task)
        self.connections.add(writer)
        self.connection_count += 1
        try:
            while line := await reader.readline():
                message = json.loads(line)
                method = message.get("method")
                if not isinstance(method, str):
                    continue
                self.methods.append(method)
                request_id = message.get("id")
                if request_id is None:
                    continue

                if method == "initialize":
                    self.initialize_received.set()
                    if self.withhold_initialize:
                        continue
                    result: dict[str, Any] = {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "tlh-fixture", "version": "1"},
                    }
                elif method == "tools/list":
                    result = {
                        "tools": [
                            {
                                "name": "fixture_tool",
                                "description": "A loopback regression fixture",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    }
                elif method == "tools/call":
                    params = message.get("params")
                    arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
                    self.call_arguments.append(arguments)
                    self.call_started.set()
                    if self.drop_calls:
                        writer.close()
                        await writer.wait_closed()
                        return
                    if self.block_calls:
                        await self.release_calls.wait()
                    result = {
                        "content": [{"type": "text", "text": "fixture-ok"}],
                        "isError": False,
                    }
                else:
                    result = {}

                writer.write(
                    (
                        json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
                        + "\n"
                    ).encode("utf-8")
                )
                await writer.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        except BaseException as exc:
            self.handler_errors.append(exc)
        finally:
            self.connections.discard(writer)
            self.closed_count += 1
            self._closed_change.set()
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task is not None:
                self.connection_tasks.discard(task)
            self._closed_change.set()

    async def wait_for_closed(self, count: int = 1, *, timeout: float = 1.0) -> None:
        async def wait() -> None:
            while self.closed_count < count or self.connections or self.connection_tasks:
                self._closed_change.clear()
                await self._closed_change.wait()

        await asyncio.wait_for(wait(), timeout)

    async def stop(self) -> None:
        if self.server is None:
            return
        self.release_calls.set()
        self.server.close()
        await self.server.wait_closed()
        for writer in tuple(self.connections):
            writer.close()
        if self.connection_tasks:
            await asyncio.wait_for(
                asyncio.gather(*tuple(self.connection_tasks), return_exceptions=True),
                timeout=1.0,
            )
        assert self.handler_errors == []


class DiscoverySequence:
    def __init__(self, ports: list[int]) -> None:
        self.ports = deque(ports)
        self.calls = 0
        self.started = asyncio.Event()
        self.block = False

    async def __call__(self) -> int:
        self.calls += 1
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        if not self.ports:
            raise AssertionError("fixture discovery was called more times than expected")
        if len(self.ports) > 1:
            return self.ports.popleft()
        return self.ports[0]


def tracked_session_factory(
    discovery: Callable[[], Awaitable[int]],
    entered_tasks: list[asyncio.Task[Any] | None],
    exited_tasks: list[asyncio.Task[Any] | None],
) -> Callable[[], Any]:
    def factory() -> Any:
        @asynccontextmanager
        async def context() -> Any:
            async with open_imcp_session(
                discovery=discovery,
                read_timeout_seconds=0.5,
                connect_timeout=0.2,
                close_timeout=0.2,
            ) as session:
                entered_tasks.append(asyncio.current_task())
                yield session
            exited_tasks.append(asyncio.current_task())

        return context()

    return factory


def make_service(
    discovery: Callable[[], Awaitable[int]],
    *,
    entered_tasks: list[asyncio.Task[Any] | None] | None = None,
    exited_tasks: list[asyncio.Task[Any] | None] | None = None,
    **kwargs: Any,
) -> BridgeService:
    entered = entered_tasks if entered_tasks is not None else []
    exited = exited_tasks if exited_tasks is not None else []
    return BridgeService(
        session_factory=tracked_session_factory(discovery, entered, exited),
        call_timeout=kwargs.pop("call_timeout", 0.5),
        setup_timeout=kwargs.pop("setup_timeout", 0.5),
        close_timeout=kwargs.pop("close_timeout", 0.2),
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
        port = await fixture.start()
        discovery = DiscoverySequence([port])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(discovery, entered_tasks=entered, exited_tasks=exited)
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
            assert discovery.calls == 1
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


def test_real_sdk_disconnect_never_replays_and_reconnects_with_fresh_discovery() -> None:
    async def scenario() -> None:
        first_fixture = FixtureMCPServer(drop_calls=True)
        second_fixture = FixtureMCPServer()
        first_port = await first_fixture.start()
        second_port = await second_fixture.start()
        discovery = DiscoverySequence([first_port, second_port])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(discovery, entered_tasks=entered, exited_tasks=exited)
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
            assert discovery.calls == 2
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


def test_real_sdk_initialize_cancellation_closes_owner_and_reconnects() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        first_fixture = FixtureMCPServer(withhold_initialize=True)
        second_fixture = FixtureMCPServer()
        first_port = await first_fixture.start()
        second_port = await second_fixture.start()
        discovery = DiscoverySequence([first_port, second_port])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(discovery, entered_tasks=entered, exited_tasks=exited)
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}},
                ),
                name="initialize-cancel-request",
            )
            await asyncio.wait_for(first_fixture.initialize_received.wait(), timeout=1.0)
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
            assert first_fixture.handler_errors == []
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
            assert discovery.calls == 2
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
        first_port = await first_fixture.start()
        second_port = await second_fixture.start()
        discovery_started = asyncio.Event()
        release_discovery = asyncio.Event()
        discovery_calls = 0

        async def discovery() -> int:
            nonlocal discovery_calls
            discovery_calls += 1
            if discovery_calls == 1:
                discovery_started.set()
                await release_discovery.wait()
                return first_port
            if discovery_calls == 2:
                return second_port
            raise AssertionError("fixture discovery was called more times than expected")

        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(discovery, entered_tasks=entered, exited_tasks=exited)
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {}},
                ),
                name="readiness-race-request",
            )
            await asyncio.wait_for(discovery_started.wait(), timeout=1.0)
            owner = service._session_owner
            assert owner is not None and owner.task is not None
            cancellation_callback_ran = asyncio.Event()

            def cancel_after_ready(_ready: asyncio.Future[Any]) -> None:
                assert owner.ready.done()
                cancellation_callback_ran.set()
                request.cancel()

            owner.ready.add_done_callback(cancel_after_ready)
            release_discovery.set()
            await asyncio.wait_for(cancellation_callback_ran.wait(), timeout=1.0)
            with pytest.raises(asyncio.CancelledError):
                await request
            await first_fixture.wait_for_closed()
            await asyncio.sleep(0)

            assert_owner_terminal(owner, expected_cancelled=True)
            assert entered == exited == [owner.task]
            assert first_fixture.call_arguments == []
            assert first_fixture.connections == set()
            assert first_fixture.connection_tasks == set()
            assert first_fixture.handler_errors == []

            later = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
            )
            second_owner = service._session_owner
            assert second_owner is not None and second_owner.task is not None
            assert second_owner.task is not owner.task
            assert later.payload["ok"] is True
            assert discovery_calls == 2
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


def test_real_sdk_setup_cancellation_stops_owner_without_a_connection() -> None:
    async def scenario() -> None:
        loop_exceptions = install_loop_exception_capture()
        fixture = FixtureMCPServer()
        port = await fixture.start()
        discovery = DiscoverySequence([port])
        discovery.block = True
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(
            discovery,
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
            await asyncio.wait_for(discovery.started.wait(), timeout=1.0)
            owner = service._session_owner
            assert owner is not None and owner.task is not None
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            await asyncio.sleep(0)

            assert_owner_terminal(owner, expected_cancelled=True)
            assert entered == exited == []
            assert service._session_owner is None
            assert fixture.connection_count == 0
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
        first_port = await first_fixture.start()
        second_port = await second_fixture.start()
        discovery = DiscoverySequence([first_port, second_port])
        entered: list[asyncio.Task[Any] | None] = []
        exited: list[asyncio.Task[Any] | None] = []
        service = make_service(discovery, entered_tasks=entered, exited_tasks=exited)
        try:
            request = asyncio.create_task(
                service.execute(
                    {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 1}},
                ),
                name="inflight-request",
            )
            await asyncio.wait_for(first_fixture.call_started.wait(), timeout=1.0)
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
            assert first_fixture.handler_errors == []
            assert len(first_fixture.call_arguments) == 1
            assert_no_pending_tasks()
            assert loop_exceptions == []

            later = await service.execute(
                {"operation": "call_tool", "name": "fixture_tool", "arguments": {"n": 2}}
            )
            second_owner = service._session_owner
            assert second_owner is not None and second_owner.task is not None
            assert later.payload["ok"] is True
            assert discovery.calls == 2
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
        idle_port = await idle_fixture.start()
        idle_entered: list[asyncio.Task[Any] | None] = []
        idle_exited: list[asyncio.Task[Any] | None] = []
        idle_service = make_service(
            DiscoverySequence([idle_port]),
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
            assert idle_fixture.handler_errors == []
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(idle_fixture)

        active_fixture = FixtureMCPServer(block_calls=True)
        active_port = await active_fixture.start()
        active_entered: list[asyncio.Task[Any] | None] = []
        active_exited: list[asyncio.Task[Any] | None] = []
        active_service = make_service(
            DiscoverySequence([active_port]),
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
            await asyncio.wait_for(active_fixture.call_started.wait(), timeout=1.0)
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
            assert active_fixture.handler_errors == []
            assert_no_pending_tasks()
            assert loop_exceptions == []
        finally:
            await close_fixture(active_fixture)

    asyncio.run(scenario())