from __future__ import annotations

import importlib
import importlib.util
import io
import json
import signal
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

import pytest


PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

import _bridge


def _load_tool(directory: str) -> ModuleType:
    path = PLUGIN_DIR / directory / "run.py"
    spec = importlib.util.spec_from_file_location(f"test_{directory}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LIST_TOOLS = _load_tool("imcp_list_tools")
CALL_TOOL = _load_tool("imcp_call")


class _RawResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _RawResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.body


class _Response(_RawResponse):
    def __init__(self, payload: object) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))


@contextmanager
def _redirect_endpoints(status: int):
    records = {"origin": [], "target": []}

    def read_request(handler: BaseHTTPRequestHandler) -> dict[str, object]:
        length = int(handler.headers.get("Content-Length", "0"))
        return {
            "authorization": handler.headers.get("Authorization"),
            "body": handler.rfile.read(length),
        }

    def quiet_log(_handler: BaseHTTPRequestHandler, _format: str, *_args: object) -> None:
        return None

    class TargetHandler(BaseHTTPRequestHandler):
        def _serve_target(self) -> None:
            records["target"].append(read_request(self))
            body = b'{"ok":true,"result":{},"truncated":false}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _serve_target
        do_POST = _serve_target
        log_message = quiet_log

    target_server = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_host, target_port = target_server.server_address
    target_url = f"http://{target_host}:{target_port}/target"

    class OriginHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            records["origin"].append(read_request(self))
            self.send_response(status)
            self.send_header("Location", target_url)
            self.send_header("Content-Length", "0")
            self.end_headers()

        log_message = quiet_log

    origin_server = ThreadingHTTPServer(("127.0.0.1", 0), OriginHandler)
    origin_host, origin_port = origin_server.server_address
    origin_url = f"http://{origin_host}:{origin_port}/origin"
    servers = (target_server, origin_server)
    threads = tuple(
        threading.Thread(target=server.serve_forever, daemon=True) for server in servers
    )
    for thread in threads:
        thread.start()
    try:
        yield origin_url, records
    finally:
        for server in servers:
            server.shutdown()
        for thread in threads:
            thread.join(timeout=2)
        for server in servers:
            server.server_close()


def _invoke_raw(module: ModuleType, raw_input: str) -> tuple[int, dict[str, object], str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.object(sys, "stdin", io.StringIO(raw_input)),
        patch.object(sys, "stdout", stdout),
        patch.object(sys, "stderr", stderr),
    ):
        result = module.main()
    return result, json.loads(stdout.getvalue()), stdout.getvalue(), stderr.getvalue()


def _invoke(module: ModuleType, params: object) -> tuple[int, dict[str, object], str, str]:
    return _invoke_raw(module, json.dumps(params))


def test_config_path_is_plugin_root_and_config_is_ignored() -> None:
    assert _bridge.CONFIG_PATH == PLUGIN_DIR / "config.json"
    assert "config.json" in (PLUGIN_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_http_opener_ignores_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable, value in {
        "http_proxy": "http://http-proxy.invalid:8080",
        "https_proxy": "http://https-proxy.invalid:8080",
        "all_proxy": "http://all-proxy.invalid:8080",
    }.items():
        monkeypatch.setenv(variable, value)

    real_build_opener = urllib_request.build_opener
    constructed_handlers: list[object] = []

    def capture_build_opener(*handlers: object) -> object:
        constructed_handlers.extend(handlers)
        return real_build_opener(*handlers)

    monkeypatch.setattr(urllib_request, "build_opener", capture_build_opener)
    importlib.reload(_bridge)

    proxy_handlers = [
        handler
        for handler in constructed_handlers
        if isinstance(handler, urllib_request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


@pytest.mark.parametrize("status", (301, 302, 303, 307, 308))
def test_redirects_are_rejected_without_following_or_replaying(
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "redirect-token"
    with _redirect_endpoints(status) as (origin_url, records):
        monkeypatch.setattr(_bridge, "load_config", lambda: (origin_url, token))

        list_code, list_payload, list_stdout, list_stderr = _invoke(LIST_TOOLS, {})
        call_code, call_payload, call_stdout, call_stderr = _invoke(
            CALL_TOOL,
            {"name": "write_once"},
        )

    assert list_code == 0
    assert list_payload == {
        "ok": False,
        "error": {"code": "bridge_unavailable", "message": "bridge request failed"},
        "truncated": False,
    }
    assert call_code == 0
    assert call_payload == _bridge.unknown_outcome_payload()
    assert token not in list_stdout + list_stderr + call_stdout + call_stderr

    assert len(records["origin"]) == 2
    assert [json.loads(request["body"]) for request in records["origin"]] == [
        {"operation": "list_tools"},
        {"operation": "call_tool", "name": "write_once", "arguments": {}},
    ]
    assert [request["authorization"] for request in records["origin"]] == [
        f"Bearer {token}",
        f"Bearer {token}",
    ]
    assert records["target"] == []


def test_list_tools_posts_bearer_request_and_preserves_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-token"
    response = {
        "ok": True,
        "result": {"tools": [{"name": "calendar_list", "inputSchema": {"type": "object"}}]},
        "truncated": False,
    }
    monkeypatch.setattr(_bridge, "load_config", lambda: ("http://bridge.invalid/bridge", token))

    with patch.object(_bridge.HTTP_OPENER, "open", return_value=_Response(response)) as urlopen:
        code, payload, _stdout, _stderr = _invoke(LIST_TOOLS, {})

    assert code == 0
    assert payload == response
    request = urlopen.call_args.args[0]
    assert json.loads(request.data) == {"operation": "list_tools"}
    assert request.get_header("Authorization") == f"Bearer {token}"
    socket_timeout = urlopen.call_args.kwargs["timeout"]
    assert _bridge.BRIDGE_OUTER_DEADLINE_SECONDS < _bridge.HTTP_TIMEOUT_SECONDS < _bridge.RUNNER_KILL_LIMIT_SECONDS
    assert socket_timeout == _bridge.HTTP_TIMEOUT_SECONDS
    assert socket_timeout <= _bridge.HTTP_TIMEOUT_SECONDS


def test_call_round_trips_nested_arguments_and_defaults_missing_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {"ok": True, "result": {"content": []}, "truncated": False}
    monkeypatch.setattr(
        _bridge,
        "load_config",
        lambda: ("http://bridge.invalid/bridge", "test-token"),
    )

    with patch.object(_bridge.HTTP_OPENER, "open", return_value=_Response(response)) as urlopen:
        code, payload, _stdout, _stderr = _invoke(
            CALL_TOOL,
            {
                "name": "calendar_create",
                "arguments": {
                    "nested": {"items": [1, {"enabled": True}]},
                    "text": "Meeting",
                },
            },
        )

    assert code == 0
    assert payload == response
    request = urlopen.call_args.args[0]
    assert json.loads(request.data) == {
        "operation": "call_tool",
        "name": "calendar_create",
        "arguments": {
            "nested": {"items": [1, {"enabled": True}]},
            "text": "Meeting",
        },
    }

    with patch.object(_bridge.HTTP_OPENER, "open", return_value=_Response(response)) as urlopen:
        code, _payload, _stdout, _stderr = _invoke(CALL_TOOL, {"name": "calendar_list"})

    assert code == 0
    assert json.loads(urlopen.call_args.args[0].data)["arguments"] == {}


def test_call_preserves_mcp_error_and_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    response = {
        "ok": False,
        "error": {
            "kind": "mcp",
            "code": 4001,
            "message": "tool rejected",
            "data": {"field": "invalid"},
        },
        "truncated": True,
    }
    monkeypatch.setattr(
        _bridge,
        "load_config",
        lambda: ("http://bridge.invalid/bridge", "test-token"),
    )

    with patch.object(_bridge.HTTP_OPENER, "open", return_value=_Response(response)):
        code, payload, _stdout, _stderr = _invoke(
            CALL_TOOL,
            {"name": "calendar_create", "arguments": {"title": "Meeting"}},
        )

    assert code == 0
    assert payload == response


@pytest.mark.parametrize(
    "params",
    [
        ({"name": "calendar_list", "unknown": True}, "unknown parameter"),
        ({"name": "calendar_list", "arguments": []}, "arguments must be a JSON object"),
    ],
)
def test_call_rejects_unknown_or_non_object_arguments(
    params: tuple[dict[str, object], str],
) -> None:
    request, message = params
    with patch.object(_bridge.HTTP_OPENER, "open") as urlopen:
        code, payload, _stdout, _stderr = _invoke(CALL_TOOL, request)

    assert code == 1
    assert payload["error"] == {"code": "invalid_input", "message": message}
    urlopen.assert_not_called()


def test_tools_reject_malformed_stdin_without_exception_text() -> None:
    with patch.object(_bridge.HTTP_OPENER, "open") as urlopen:
        code, payload, stdout, stderr = _invoke_raw(CALL_TOOL, "{not-json")

    assert code == 1
    assert payload["error"]["code"] == "invalid_input"
    assert stdout.startswith("{")
    assert stderr == ""
    urlopen.assert_not_called()


def test_missing_and_malformed_config_are_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "config-secret"
    missing = tmp_path / "missing-config.json"
    monkeypatch.setattr(_bridge, "CONFIG_PATH", missing)
    code, payload, stdout, stderr = _invoke(LIST_TOOLS, {})
    assert code == 0
    assert payload["error"]["code"] == "configuration_error"
    assert secret not in stdout + stderr

    malformed = tmp_path / "malformed-config.json"
    malformed.write_text(f'{{"bridge_token": "{secret}"', encoding="utf-8")
    monkeypatch.setattr(_bridge, "CONFIG_PATH", malformed)
    code, payload, stdout, stderr = _invoke(LIST_TOOLS, {})
    assert code == 0
    assert payload["error"]["code"] == "configuration_error"
    assert secret not in stdout + stderr


def test_credential_bearing_url_is_rejected_without_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "url-secret"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "bridge_url": f"http://user:{secret}@bridge.invalid/bridge",
                "bridge_token": secret,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_bridge, "CONFIG_PATH", config)

    with patch.object(_bridge.HTTP_OPENER, "open") as urlopen:
        code, payload, stdout, stderr = _invoke(LIST_TOOLS, {})

    assert code == 0
    assert payload["error"]["code"] == "configuration_error"
    assert secret not in stdout + stderr
    urlopen.assert_not_called()


def test_http_exception_text_and_token_are_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "very-secret-token"
    monkeypatch.setattr(_bridge, "load_config", lambda: ("http://bridge.invalid/secret", secret))

    with patch.object(
        _bridge.HTTP_OPENER,
        "open",
        side_effect=URLError(f"failed to reach {secret}"),
    ):
        code, payload, stdout, stderr = _invoke(LIST_TOOLS, {})

    assert code == 0
    assert payload == {
        "ok": False,
        "error": {"code": "bridge_unavailable", "message": "bridge request failed"},
        "truncated": False,
    }
    assert secret not in stdout + stderr


def test_http_error_body_is_structured_but_redacts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "secret-token"
    body = json.dumps(
        {
            "ok": False,
            "error": {"kind": "mcp", "message": f"upstream echoed {secret}", "data": {"token": secret}},
            "truncated": False,
        }
    ).encode("utf-8")
    response = HTTPError(
        "http://bridge.invalid/bridge",
        502,
        f"failure {secret}",
        hdrs=None,
        fp=io.BytesIO(body),
    )
    monkeypatch.setattr(_bridge, "load_config", lambda: ("http://bridge.invalid/bridge", secret))

    with patch.object(_bridge.HTTP_OPENER, "open", side_effect=response):
        code, payload, stdout, stderr = _invoke(LIST_TOOLS, {})

    assert code == 0
    assert payload["error"] == {
        "kind": "mcp",
        "message": "upstream echoed [REDACTED]",
        "data": {"token": "[REDACTED]"},
    }
    assert payload["truncated"] is False
    assert secret not in stdout + stderr


def test_invalid_and_oversized_call_responses_are_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "post-dispatch-secret"
    monkeypatch.setattr(_bridge, "load_config", lambda: ("http://bridge.invalid/bridge", secret))

    with patch.object(
        _bridge.HTTP_OPENER,
        "open",
        return_value=_RawResponse(b"not-json"),
    ) as urlopen:
        code, payload, stdout, stderr = _invoke(CALL_TOOL, {"name": "write_once"})

    assert code == 0
    assert payload == _bridge.unknown_outcome_payload()
    assert secret not in stdout + stderr
    urlopen.assert_called_once()

    with patch.object(
        _bridge.HTTP_OPENER,
        "open",
        return_value=_RawResponse(b"x" * (_bridge.MAX_RESPONSE_BYTES + 1)),
    ) as urlopen:
        code, payload, stdout, stderr = _invoke(CALL_TOOL, {"name": "write_once"})

    assert code == 0
    assert payload == _bridge.unknown_outcome_payload()
    assert secret not in stdout + stderr
    urlopen.assert_called_once()


def test_post_dispatch_transport_failure_is_unknown_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "transport-secret"
    monkeypatch.setattr(_bridge, "load_config", lambda: ("http://bridge.invalid/bridge", secret))
    failures = (
        TimeoutError(f"timed out after {secret}"),
        ConnectionResetError(f"connection reset after {secret}"),
        URLError(f"transport failed after {secret}"),
    )

    for failure in failures:
        with patch.object(_bridge.HTTP_OPENER, "open", side_effect=failure) as urlopen:
            code, payload, stdout, stderr = _invoke(CALL_TOOL, {"name": "write_once"})

        assert code == 0
        assert payload == _bridge.unknown_outcome_payload()
        assert secret not in stdout + stderr
        urlopen.assert_called_once()


@pytest.mark.skipif(
    not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"),
    reason="requires the Unix signal timer used by the plugin runner",
)
def test_total_deadline_interrupts_and_restores_signal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    original_handler = signal.getsignal(signal.SIGALRM)
    original_timer = signal.getitimer(signal.ITIMER_REAL)
    marker = lambda _signum, _frame: None
    signal.signal(signal.SIGALRM, marker)
    signal.setitimer(signal.ITIMER_REAL, 60.0, 0.0)
    monkeypatch.setattr(_bridge, "HTTP_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(_bridge, "load_config", lambda: ("http://bridge.invalid/bridge", "timer-token"))

    def slow_urlopen(_request: object, *, timeout: float) -> _Response:
        del timeout
        time.sleep(0.5)
        return _Response({"ok": True, "result": {}, "truncated": False})

    started = time.monotonic()
    try:
        with patch.object(_bridge.HTTP_OPENER, "open", side_effect=slow_urlopen):
            payload = _bridge.request_bridge({"operation": "list_tools"})
        elapsed = time.monotonic() - started

        assert elapsed < 0.25
        assert payload["error"]["code"] == "bridge_unavailable"
        assert signal.getsignal(signal.SIGALRM) is marker
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        assert 0 < remaining <= 60.0
        assert interval == 0.0
    finally:
        signal.setitimer(signal.ITIMER_REAL, *original_timer)
        signal.signal(signal.SIGALRM, original_handler)
