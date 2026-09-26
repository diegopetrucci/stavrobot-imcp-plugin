from __future__ import annotations

import asyncio
import concurrent.futures
import io
import json
import logging
import threading
import time
from contextlib import redirect_stderr
from pathlib import Path
from http.client import HTTPConnection
from unittest.mock import patch
from typing import Any

import pytest
from mcp import MCPError, types

from bridge.server import (
    DEFAULT_CALL_TIMEOUT,
    DEFAULT_RUNTIME_TIMEOUT,
    DEFAULT_SETUP_TIMEOUT,
    MAX_REQUEST_BODY_BYTES,
    MAX_RESPONSE_BYTES,
    AsyncBridgeRuntime,
    BridgeConfigurationError,
    BridgeHTTPServer,
    BridgeRequestHandler,
    BridgeService,
    LOGGER,
    _configure_logging,
    load_allowlist,
    load_token,
    main,
)


class FakeSession:
    def __init__(self, *, call_results: list[Any] | None = None, tool_text: str = "ok") -> None:
        self.call_results = list(call_results or [])
        self.tool_text = tool_text
        self.initialize_calls = 0
        self.call_calls: list[tuple[str, dict[str, Any]]] = []
        self.list_calls = 0

    async def initialize(self) -> None:
        self.initialize_calls += 1

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        read_timeout_seconds: float | None = None,
    ) -> Any:
        del read_timeout_seconds
        self.call_calls.append((name, arguments))
        if self.call_results:
            result = self.call_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=self.tool_text)],
            structuredContent={"@type": "Thing", "name": self.tool_text},
        )

    async def list_tools(self, *, params: Any = None) -> types.ListToolsResult:
        del params
        self.list_calls += 1
        return types.ListToolsResult(
            tools=[
                types.Tool(name="allowed", inputSchema={"type": "object"}),
                types.Tool(name="blocked", inputSchema={"type": "object"}),
            ]
        )


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.entered = 0
        self.exited = 0
        self.closed_event = threading.Event()

    async def __aenter__(self) -> FakeSession:
        self.entered += 1
        return self.session

    async def __aexit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        self.exited += 1
        self.closed_event.set()


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def start_http(
    service: BridgeService,
    *,
    token: str = "test-token",
    runtime_timeout: float | None = None,
) -> tuple[BridgeHTTPServer, AsyncBridgeRuntime, threading.Thread]:
    runtime = AsyncBridgeRuntime(service)
    runtime.start()
    server = BridgeHTTPServer(
        ("127.0.0.1", 0),
        BridgeRequestHandler,
        token=token,
        bridge_path="/bridge",
        runtime=runtime,
        runtime_timeout=runtime_timeout,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, runtime, thread


def request_with_raw(
    server: BridgeHTTPServer,
    body: bytes | str,
    *,
    token: str = "test-token",
) -> tuple[int, dict[str, Any], bytes]:
    if isinstance(body, str):
        body = body.encode("utf-8")
    address, port = server.server_address
    connection = HTTPConnection(address, port, timeout=2)
    try:
        connection.request(
            "POST",
            "/bridge",
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw), raw
    finally:
        connection.close()


def request(
    server: BridgeHTTPServer,
    body: bytes | str,
    *,
    token: str = "test-token",
) -> tuple[int, dict[str, Any]]:
    status, payload, _raw = request_with_raw(server, body, token=token)
    return status, payload


def stop_http(server: BridgeHTTPServer, runtime: AsyncBridgeRuntime, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()
    runtime.close()


def test_auth_failure_does_not_open_mcp_session() -> None:
    created = 0

    def factory() -> FakeSessionContext:
        nonlocal created
        created += 1
        return FakeSessionContext(FakeSession())

    service = BridgeService(session_factory=factory)
    server, runtime, thread = start_http(service)
    try:
        status, payload = request(server, '{"operation":"health"}', token="wrong-token")
    finally:
        stop_http(server, runtime, thread)

    assert status == 401
    assert payload["error"]["code"] == "unauthorized"
    assert created == 0


def test_allowlist_rejection_happens_before_dispatch() -> None:
    created = 0

    def factory() -> FakeSessionContext:
        nonlocal created
        created += 1
        return FakeSessionContext(FakeSession())

    response = run(
        BridgeService(allowlist=("allowed",), session_factory=factory).execute(
            {"operation": "call_tool", "name": "blocked", "arguments": {}}
        )
    )

    assert response.status_code == 403
    assert response.payload["error"]["code"] == "tool_not_allowed"
    assert created == 0


def test_cold_setup_bound_covers_two_discovery_windows_and_connect() -> None:
    class SlowContext(FakeSessionContext):
        async def __aenter__(self) -> FakeSession:
            await asyncio.sleep(setup_delay)
            return await super().__aenter__()

    discovery_timeout = 0.1
    connect_timeout = 0.1
    # Keep enough slack for a busy CI event loop while still exceeding either
    # individual phase timeout.  The assertion below continues to verify that
    # setup is bounded by both discovery windows plus connect.
    setup_delay = (discovery_timeout * 2) + connect_timeout - 0.1
    context = SlowContext(FakeSession())
    service = BridgeService(
        session_factory=lambda: context,
        call_timeout=0.2,
        discovery_timeout=discovery_timeout,
        connect_timeout=connect_timeout,
    )

    server, runtime, thread = start_http(service)
    try:
        status, payload = request(
            server,
            json.dumps({"operation": "call_tool", "name": "cold", "arguments": {}}),
        )
    finally:
        stop_http(server, runtime, thread)

    assert status == 200
    assert payload["ok"] is True
    assert context.entered == 1
    assert service._setup_timeout == pytest.approx(
        discovery_timeout * 2 + connect_timeout
    )


def test_cold_setup_timeout_can_be_configured_separately() -> None:
    service = BridgeService(
        discovery_timeout=0.01,
        connect_timeout=0.01,
        setup_timeout=0.5,
    )

    assert service._setup_timeout == 0.5


def test_default_runtime_deadline_is_below_synchronous_plugin_limit() -> None:
    runtime = AsyncBridgeRuntime(BridgeService())
    server = BridgeHTTPServer(
        ("127.0.0.1", 0),
        BridgeRequestHandler,
        token="test-token",
        runtime=runtime,
    )
    try:
        assert DEFAULT_CALL_TIMEOUT == 10.0
        assert BridgeService()._setup_timeout == DEFAULT_SETUP_TIMEOUT
        assert server.runtime_timeout == pytest.approx(DEFAULT_RUNTIME_TIMEOUT)
        assert server.runtime_timeout < 20.0
    finally:
        server.server_close()
        runtime.close()


def test_server_error_handler_suppresses_unsanitized_traceback() -> None:
    runtime = AsyncBridgeRuntime(BridgeService())
    server = BridgeHTTPServer(
        ("127.0.0.1", 0),
        BridgeRequestHandler,
        token="test-token",
        runtime=runtime,
    )
    payload = "payload-like request content"
    client_host = "client-address-with-payload"
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            try:
                raise RuntimeError(payload)
            except RuntimeError:
                server.handle_error(None, (client_host, 4321))
    finally:
        server.server_close()
        runtime.close()

    output = stderr.getvalue()
    assert output == ""
    assert payload not in output
    assert client_host not in output
    assert "Traceback" not in output


def test_request_body_limit_is_rejected_without_dispatch() -> None:
    created = 0

    def factory() -> FakeSessionContext:
        nonlocal created
        created += 1
        return FakeSessionContext(FakeSession())

    service = BridgeService(session_factory=factory)
    server, runtime, thread = start_http(service)
    try:
        status, payload = request(server, b"x" * (MAX_REQUEST_BODY_BYTES + 1))
    finally:
        stop_http(server, runtime, thread)

    assert status == 413
    assert payload["error"]["code"] == "request_too_large"
    assert created == 0


def test_malformed_input_is_rejected_without_dispatch() -> None:
    created = 0

    def factory() -> FakeSessionContext:
        nonlocal created
        created += 1
        return FakeSessionContext(FakeSession())

    service = BridgeService(session_factory=factory)
    server, runtime, thread = start_http(service)
    try:
        status, payload = request(server, b"{not-json")
    finally:
        stop_http(server, runtime, thread)

    assert status == 400
    assert payload["error"]["code"] == "invalid_request"
    assert created == 0


def test_response_truncation_is_bounded_and_explicit() -> None:
    huge_result = types.CallToolResult(
        content=[types.TextContent(type="text", text="x" * (MAX_RESPONSE_BYTES * 2))],
        structuredContent={"@type": "Thing", "description": "y" * 1000},
    )
    session = FakeSession(call_results=[huge_result])

    def factory() -> FakeSessionContext:
        return FakeSessionContext(session)

    service = BridgeService(session_factory=factory)
    server, runtime, thread = start_http(service)
    try:
        status, payload, raw = request_with_raw(
            server,
            json.dumps(
                {"operation": "call_tool", "name": "large", "arguments": {}},
                separators=(",", ":"),
            ),
        )
    finally:
        stop_http(server, runtime, thread)

    assert status == 200
    assert len(raw) <= MAX_RESPONSE_BYTES
    assert payload["ok"] is True
    assert payload["truncated"] is True


def test_mcp_error_keeps_structured_code_and_data() -> None:
    error = MCPError(1234, "tool rejected", {"@type": "Error", "fields": ["x"]})
    session = FakeSession(call_results=[error])
    service = BridgeService(session_factory=lambda: FakeSessionContext(session))

    response = run(
        service.execute(
            {"operation": "call_tool", "name": "known_error", "arguments": {}}
        )
    )

    assert response.payload == {
        "ok": False,
        "error": {
            "kind": "mcp",
            "code": 1234,
            "message": "tool rejected",
            "data": {"@type": "Error", "fields": ["x"]},
        },
        "truncated": False,
    }


def test_per_call_timeout_returns_unknown_without_replay() -> None:
    class SlowSession(FakeSession):
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            read_timeout_seconds: float | None = None,
        ) -> Any:
            del name, arguments, read_timeout_seconds
            await asyncio.sleep(1)
            return types.CallToolResult(content=[])

    session = SlowSession()
    created = 0

    def factory() -> FakeSessionContext:
        nonlocal created
        created += 1
        return FakeSessionContext(session)

    service = BridgeService(session_factory=factory, call_timeout=0.01)
    started = time.monotonic()
    response = run(
        service.execute(
            {"operation": "call_tool", "name": "slow", "arguments": {}}
        )
    )

    assert response.payload["error"]["code"] == "unknown_outcome"
    assert created == 1
    assert time.monotonic() - started < 0.5


def test_dead_session_is_not_retried_and_next_call_rediscoveries() -> None:
    first = FakeSession(call_results=[MCPError(types.CONNECTION_CLOSED, "closed")])
    second = FakeSession(tool_text="fresh-session")
    contexts = [FakeSessionContext(first), FakeSessionContext(second)]
    created: list[FakeSessionContext] = []

    def factory() -> FakeSessionContext:
        context = contexts[len(created)]
        created.append(context)
        return context

    service = BridgeService(session_factory=factory, call_timeout=0.2)
    first_response = run(
        service.execute(
            {"operation": "call_tool", "name": "write_once", "arguments": {"value": "x"}}
        )
    )

    assert first_response.payload["error"]["code"] == "unknown_outcome"
    assert len(created) == 1
    assert len(first.call_calls) == 1

    second_response = run(
        service.execute(
            {"operation": "call_tool", "name": "write_once", "arguments": {"value": "x"}}
        )
    )
    assert second_response.payload["ok"] is True
    assert len(created) == 2
    assert len(first.call_calls) == 1
    assert second.call_calls == [("write_once", {"value": "x"})]


def test_deep_result_serialization_is_unknown_and_reconnects() -> None:
    recursive: list[Any] = []
    recursive.append(recursive)
    first = FakeSession(call_results=[recursive])
    second = FakeSession(tool_text="after-serialization-failure")
    contexts = [FakeSessionContext(first), FakeSessionContext(second)]
    created: list[FakeSessionContext] = []

    def factory() -> FakeSessionContext:
        context = contexts[len(created)]
        created.append(context)
        return context

    service = BridgeService(session_factory=factory)
    first_response = run(service.execute({"operation": "call_tool", "name": "deep", "arguments": {}}))
    second_response = run(service.execute({"operation": "call_tool", "name": "deep", "arguments": {}}))

    assert first_response.status_code == 502
    assert first_response.payload == {
        "ok": False,
        "error": {
            "code": "unknown_outcome",
            "message": "tool call outcome is unknown; the call was not retried",
            "retryable": False,
        },
        "truncated": False,
    }
    assert second_response.payload["ok"] is True
    assert len(created) == 2
    assert len(first.call_calls) == 1
    assert len(second.call_calls) == 1


def test_list_tools_filters_allowlist_and_health_distinguishes_states() -> None:
    session = FakeSession()

    service = BridgeService(allowlist=("allowed",), session_factory=lambda: FakeSessionContext(session))
    before = run(service.execute({"operation": "health"}))
    assert before.payload["result"] == {
        "bridge_up": True,
        "mcp_session_up": False,
        "imcp_app_reachable": None,
    }

    listed = run(service.execute({"operation": "list_tools"}))
    assert listed.payload["ok"] is True
    assert [tool["name"] for tool in listed.payload["result"]["tools"]] == ["allowed"]

    after = run(service.execute({"operation": "health"}))
    assert after.payload["result"]["mcp_session_up"] is True
    assert after.payload["result"]["imcp_app_reachable"] is True


def test_logs_do_not_include_arguments_results_hosts_or_token(caplog: pytest.LogCaptureFixture) -> None:
    service = BridgeService(session_factory=lambda: FakeSessionContext(FakeSession(tool_text="PRIVATE_RESULT")))
    server, runtime, thread = start_http(service, token="PRIVATE_TOKEN")
    caplog.set_level(logging.INFO, logger="imcp.bridge")
    try:
        status, payload = request(
            server,
            json.dumps(
                {
                    "operation": "call_tool",
                    "name": "safe_tool",
                    "arguments": {"secret": "PRIVATE_ARGUMENT"},
                }
            ),
            token="PRIVATE_TOKEN",
        )
    finally:
        stop_http(server, runtime, thread)

    assert status == 200
    assert payload["ok"] is True
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "tool=safe_tool" in messages
    assert "PRIVATE_ARGUMENT" not in messages
    assert "PRIVATE_RESULT" not in messages
    assert "PRIVATE_TOKEN" not in messages
    assert "127.0.0.1" not in messages


def test_truncation_preserves_error_and_structured_content_semantics() -> None:
    from bridge.server import _encode_json

    payload = {
        "ok": True,
        "result": {
            "content": [{"type": "text", "text": "x" * (MAX_RESPONSE_BYTES * 2)}],
            "isError": True,
            "structuredContent": {"@type": "Error", "message": "preserve-me"},
        },
        "truncated": False,
    }

    encoded, truncated = _encode_json(payload)
    decoded = json.loads(encoded)

    assert truncated is True
    assert len(encoded) <= MAX_RESPONSE_BYTES
    assert decoded["truncated"] is True
    assert decoded["result"]["isError"] is True
    assert isinstance(decoded["result"]["structuredContent"], dict)
    assert decoded["result"]["structuredContent"]["message"] == "preserve-me"


def test_truncation_many_small_items_keeps_linear_output_work() -> None:
    from bridge.server import _encode_json

    payload = {
        "ok": True,
        "result": {
            "content": [{"type": "text", "text": "small"} for _ in range(20_000)],
            "isError": True,
            "structuredContent": {"kind": "bounded"},
        },
        "truncated": False,
    }

    encoded, truncated = _encode_json(payload, limit=8_192)
    decoded = json.loads(encoded)

    assert truncated is True
    assert len(encoded) <= 8_192
    assert decoded["result"]["isError"] is True
    assert decoded["result"]["structuredContent"] == {"kind": "bounded"}
    assert isinstance(decoded["result"].get("content"), list)


def test_response_too_large_fallback_is_error_for_mixed_unicode() -> None:
    from bridge.server import _encode_json

    lone_surrogate = chr(0xD800)
    payload = {
        "ok": True,
        "result": {
            "content": [{"type": "text", "text": ((lone_surrogate + "é") * 512)}],
            "structuredContent": {"kind": "unicode"},
        },
        "top_level_" + ("é" * 1_024): lone_surrogate + "é",
        "truncated": False,
    }

    encoded, truncated = _encode_json(payload, limit=256)
    decoded = json.loads(encoded)

    assert truncated is True
    assert len(encoded) <= 256
    assert decoded["ok"] is False
    assert decoded["error"]["code"] == "response_too_large"
    assert decoded["truncated"] is True


def test_health_is_nonblocking_during_an_inflight_mcp_call() -> None:
    class BlockingSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            read_timeout_seconds: float | None = None,
        ) -> Any:
            self.started.set()
            await self.release.wait()
            return await super().call_tool(
                name,
                arguments,
                read_timeout_seconds=read_timeout_seconds,
            )

    session = BlockingSession()
    context = FakeSessionContext(session)

    async def scenario() -> None:
        service = BridgeService(session_factory=lambda: context)
        call_task = asyncio.create_task(
            service.execute({"operation": "call_tool", "name": "blocked", "arguments": {}})
        )
        await asyncio.wait_for(session.started.wait(), timeout=1)

        health = await asyncio.wait_for(service.execute({"operation": "health"}), timeout=0.1)
        assert health.payload["result"] == {
            "bridge_up": True,
            "mcp_session_up": True,
            "imcp_app_reachable": True,
        }

        session.release.set()
        await call_task

    run(scenario())


def test_health_reports_false_after_transport_evidence() -> None:
    session = FakeSession(call_results=[MCPError(types.CONNECTION_CLOSED, "closed")])
    service = BridgeService(session_factory=lambda: FakeSessionContext(session))

    response = run(service.execute({"operation": "call_tool", "name": "once", "arguments": {}}))
    health = run(service.execute({"operation": "health"}))

    assert response.payload["error"]["code"] == "unknown_outcome"
    assert health.payload["result"]["mcp_session_up"] is False
    assert health.payload["result"]["imcp_app_reachable"] is False


def test_default_factory_reconnects_with_fresh_transport_options() -> None:
    first = FakeSession(call_results=[MCPError(types.CONNECTION_CLOSED, "closed")])
    second = FakeSession(tool_text="second-session")
    contexts = [FakeSessionContext(first), FakeSessionContext(second)]
    opened: list[dict[str, Any]] = []

    def fake_open(**kwargs: Any) -> FakeSessionContext:
        opened.append(kwargs)
        return contexts[len(opened) - 1]

    service = BridgeService(call_timeout=0.25, discovery_timeout=0.3, connect_timeout=0.4, close_timeout=0.5)
    with patch("bridge.server.open_imcp_session", side_effect=fake_open):
        first_response = run(
            service.execute({"operation": "call_tool", "name": "once", "arguments": {}})
        )
        second_response = run(
            service.execute({"operation": "call_tool", "name": "once", "arguments": {}})
        )

    assert first_response.payload["error"]["code"] == "unknown_outcome"
    assert second_response.payload["ok"] is True
    assert len(opened) == 2
    for options in opened:
        assert options["discovery_timeout"] == 0.3
        assert options["connect_timeout"] == 0.4
        assert options["close_timeout"] == 0.5
    assert len(first.call_calls) == 1
    assert len(second.call_calls) == 1


def test_non_transport_mcp_error_keeps_session_reusable() -> None:
    session = FakeSession(call_results=[MCPError(4001, "rejected"), types.CallToolResult(content=[])])
    created = 0

    def factory() -> FakeSessionContext:
        nonlocal created
        created += 1
        return FakeSessionContext(session)

    service = BridgeService(session_factory=factory)
    first = run(service.execute({"operation": "call_tool", "name": "same", "arguments": {}}))
    second = run(service.execute({"operation": "call_tool", "name": "same", "arguments": {}}))

    assert first.payload["error"]["code"] == 4001
    assert second.payload["ok"] is True
    assert created == 1
    assert len(session.call_calls) == 2


def test_outer_runtime_timeout_is_unknown_and_never_replayed() -> None:
    class SlowSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            read_timeout_seconds: float | None = None,
        ) -> Any:
            del name, arguments, read_timeout_seconds
            self.call_calls.append(("once", {}))
            self.started.set()
            while True:
                await asyncio.sleep(0.001)

    first = SlowSession()
    second = FakeSession(tool_text="fresh")
    contexts = [FakeSessionContext(first), FakeSessionContext(second)]
    created: list[FakeSessionContext] = []

    def factory() -> FakeSessionContext:
        context = contexts[len(created)]
        created.append(context)
        return context

    service = BridgeService(session_factory=factory, call_timeout=1.0)
    server, runtime, thread = start_http(service, runtime_timeout=0.02)
    try:
        status, payload = request(
            server,
            json.dumps({"operation": "call_tool", "name": "once", "arguments": {}}),
        )
        assert status == 502
        assert payload["error"]["code"] == "unknown_outcome"
        assert first.started.is_set()
        assert contexts[0].closed_event.wait(timeout=1)

        second_status, second_payload = request(
            server,
            json.dumps({"operation": "call_tool", "name": "once", "arguments": {}}),
        )
    finally:
        stop_http(server, runtime, thread)

    assert second_status == 200
    assert second_payload["ok"] is True
    assert len(created) == 2
    assert len(first.call_calls) == 1
    assert len(second.call_calls) == 1


def test_http_cancelled_runtime_future_is_unknown_and_reconnects() -> None:
    class CancellableSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            read_timeout_seconds: float | None = None,
        ) -> Any:
            del name, arguments, read_timeout_seconds
            self.call_calls.append(("cancelled", {}))
            self.started.set()
            while True:
                await asyncio.sleep(0.001)

    first = CancellableSession()
    second = FakeSession(tool_text="after-cancellation")
    contexts = [FakeSessionContext(first), FakeSessionContext(second)]
    created: list[FakeSessionContext] = []

    def factory() -> FakeSessionContext:
        context = contexts[len(created)]
        created.append(context)
        return context

    service = BridgeService(session_factory=factory, call_timeout=1.0)
    runtime = AsyncBridgeRuntime(service)
    runtime.start()
    original_run = runtime.run
    cancel_once = True

    def cancel_first(awaitable: Any, *, timeout: float) -> Any:
        nonlocal cancel_once
        if cancel_once:
            cancel_once = False
            future = asyncio.run_coroutine_threadsafe(awaitable, runtime.loop)
            assert first.started.wait(timeout=1)
            assert future.cancel()
            with pytest.raises(concurrent.futures.CancelledError):
                future.result(timeout=1)
            raise AssertionError("cancelled future unexpectedly returned")
        return original_run(awaitable, timeout=timeout)

    runtime.run = cancel_first  # type: ignore[method-assign]
    server = BridgeHTTPServer(
        ("127.0.0.1", 0),
        BridgeRequestHandler,
        token="test-token",
        bridge_path="/bridge",
        runtime=runtime,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = request(
            server,
            json.dumps({"operation": "call_tool", "name": "cancelled", "arguments": {}}),
        )
        assert status == 502
        assert payload["error"]["code"] == "unknown_outcome"
        assert payload["error"]["retryable"] is False
        assert contexts[0].closed_event.wait(timeout=1)

        second_status, second_payload = request(
            server,
            json.dumps({"operation": "call_tool", "name": "cancelled", "arguments": {}}),
        )
    finally:
        stop_http(server, runtime, thread)

    assert second_status == 200
    assert second_payload["ok"] is True
    assert len(first.call_calls) == 1
    assert len(second.call_calls) == 1
    assert len(created) == 2


def test_http_generic_call_runtime_failure_is_unknown() -> None:
    service = BridgeService()
    server, runtime, thread = start_http(service)

    def fail_runtime(awaitable: Any, *, timeout: float) -> Any:
        del timeout
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise RuntimeError("simulated runtime failure")

    runtime.run = fail_runtime  # type: ignore[method-assign]
    try:
        status, payload = request(
            server,
            json.dumps({"operation": "call_tool", "name": "runtime-failure", "arguments": {}}),
        )
    finally:
        stop_http(server, runtime, thread)

    assert status == 502
    assert payload["error"]["code"] == "unknown_outcome"
    assert payload["error"]["retryable"] is False


def test_runtime_immediate_close_closes_unstarted_loop() -> None:
    runtime = AsyncBridgeRuntime(BridgeService())

    runtime.close()
    runtime.close()

    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()
    with pytest.raises(RuntimeError):
        runtime.start()


def test_runtime_start_is_thread_safe_and_close_is_deterministic() -> None:
    runtime = AsyncBridgeRuntime(BridgeService())
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def starter() -> None:
        try:
            barrier.wait(timeout=2)
            runtime.start()
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    starters = [threading.Thread(target=starter) for _ in range(8)]
    for thread in starters:
        thread.start()
    for thread in starters:
        thread.join(timeout=2)

    try:
        assert errors == []
        assert runtime._thread.is_alive()
        assert runtime.loop.is_running()
    finally:
        runtime.close()

    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()


def test_runtime_start_close_race_leaves_no_live_loop() -> None:
    runtime = AsyncBridgeRuntime(BridgeService())
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def starter() -> None:
        try:
            barrier.wait(timeout=2)
            runtime.start()
        except RuntimeError:
            pass
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    def closer() -> None:
        barrier.wait(timeout=2)
        runtime.close()

    start_thread = threading.Thread(target=starter)
    close_thread = threading.Thread(target=closer)
    start_thread.start()
    close_thread.start()
    start_thread.join(timeout=2)
    close_thread.join(timeout=2)

    assert errors == []
    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()


def test_token_and_allowlist_configuration_validation(tmp_path: Path) -> None:
    valid_token = tmp_path / "token"
    valid_token.write_text("secret\n", encoding="utf-8")
    assert load_token(valid_token) == "secret"

    for index, contents in enumerate(("", "   ", "has whitespace")):
        path = tmp_path / f"bad-token-{index}"
        path.write_text(contents, encoding="utf-8")
        with pytest.raises(BridgeConfigurationError):
            load_token(path)

    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps({"tools": ["one", "two"]}), encoding="utf-8")
    assert load_allowlist(allowlist) == frozenset({"one", "two"})
    assert load_allowlist(None) == frozenset({"*"})

    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"tools": [""]}), encoding="utf-8")
    with pytest.raises(BridgeConfigurationError):
        load_allowlist(invalid)
    invalid.write_text(json.dumps({"tools": [1]}), encoding="utf-8")
    with pytest.raises(BridgeConfigurationError):
        load_allowlist(invalid)


def test_main_isolates_bridge_logging_from_root_and_third_party_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    original_root_handlers = list(root.handlers)
    original_root_level = root.level
    original_last_resort = logging.lastResort
    original_bridge_handlers = list(LOGGER.handlers)
    original_bridge_level = LOGGER.level
    original_bridge_propagate = LOGGER.propagate
    third_party_loggers = [logging.getLogger(name) for name in ("mcp", "zeroconf", "asyncio")]
    original_third_party_state = [
        (list(logger.handlers), logger.level, logger.propagate, logger.disabled) for logger in third_party_loggers
    ]
    fallback_logger = logging.getLogger("representative.third_party.no_handler")
    original_fallback_state = (
        list(fallback_logger.handlers),
        fallback_logger.level,
        fallback_logger.propagate,
        fallback_logger.disabled,
    )
    output = io.StringIO()

    def fail_basic_config(**_kwargs: Any) -> None:
        raise AssertionError("CLI startup must not configure the root logger")

    monkeypatch.setattr(logging, "basicConfig", fail_basic_config)
    try:
        for logger in third_party_loggers:
            logger.handlers.clear()
            logger.setLevel(logging.INFO)
            logger.propagate = True
            logger.disabled = False
        fallback_logger.handlers.clear()
        fallback_logger.setLevel(logging.INFO)
        fallback_logger.propagate = False
        fallback_logger.disabled = False

        with redirect_stderr(output):
            result = main(["--token-file", str(tmp_path / "missing-token")])
            _configure_logging()
            assert len(LOGGER.handlers) == 1
            assert isinstance(LOGGER.handlers[0], logging.StreamHandler)
            assert LOGGER.handlers[0].level == logging.INFO
            assert LOGGER.handlers[0].formatter is not None
            assert LOGGER.handlers[0].formatter._fmt == "%(message)s"
            assert LOGGER.propagate is False

            LOGGER.info("tool=safe_tool status=ok duration_ms=7")
            logging.getLogger("mcp").info("mcp INFO payload=private")
            logging.getLogger("zeroconf").warning("zeroconf WARNING host=private")
            logging.getLogger("asyncio").error("asyncio ERROR payload=private")
            fallback_logger.error("lastResort payload=private")

        assert result == 1
        messages = output.getvalue()
        assert "tool=safe_tool status=ok duration_ms=7" in messages
        assert "mcp INFO payload=private" not in messages
        assert "zeroconf WARNING host=private" not in messages
        assert "asyncio ERROR payload=private" not in messages
        assert "lastResort payload=private" not in messages
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in original_root_handlers:
            root.addHandler(handler)
        root.setLevel(original_root_level)
        logging.lastResort = original_last_resort

        for handler in list(LOGGER.handlers):
            LOGGER.removeHandler(handler)
        for handler in original_bridge_handlers:
            LOGGER.addHandler(handler)
        LOGGER.setLevel(original_bridge_level)
        LOGGER.propagate = original_bridge_propagate

        for logger, state in zip(third_party_loggers, original_third_party_state):
            handlers, level, propagate, disabled = state
            logger.handlers[:] = handlers
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled
        handlers, level, propagate, disabled = original_fallback_state
        fallback_logger.handlers[:] = handlers
        fallback_logger.setLevel(level)
        fallback_logger.propagate = propagate
        fallback_logger.disabled = disabled


def test_list_tools_paginates_and_rejects_repeated_cursor() -> None:
    class PagedSession(FakeSession):
        async def list_tools(self, *, params: Any = None) -> types.ListToolsResult:
            self.list_calls += 1
            if params is None:
                return types.ListToolsResult(
                    tools=[types.Tool(name="one", inputSchema={"type": "object"})],
                    nextCursor="page-two",
                )
            return types.ListToolsResult(
                tools=[types.Tool(name="two", inputSchema={"type": "object"})],
            )

    paged = PagedSession()
    service = BridgeService(session_factory=lambda: FakeSessionContext(paged))
    response = run(service.execute({"operation": "list_tools"}))

    assert response.payload["ok"] is True
    assert [tool["name"] for tool in response.payload["result"]["tools"]] == ["one", "two"]
    assert paged.list_calls == 2

    class RepeatingSession(PagedSession):
        async def list_tools(self, *, params: Any = None) -> types.ListToolsResult:
            self.list_calls += 1
            return types.ListToolsResult(
                tools=[],
                nextCursor="same",
            )

    repeating = RepeatingSession()
    repeated = BridgeService(session_factory=lambda: FakeSessionContext(repeating))
    repeated_response = run(repeated.execute({"operation": "list_tools"}))

    assert repeated_response.status_code == 502
    assert repeated_response.payload["error"]["code"] == "invalid_mcp_response"
    assert repeating.list_calls == 2
