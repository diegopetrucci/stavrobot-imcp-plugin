from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_bridge.sh"
TOKEN = "fixture-token-that-must-not-be-printed"
TOOL_METADATA = "private-tool-metadata-that-must-not-be-printed"


def _embedded_program() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start_marker = "exec python3 - <<'PY'\n"
    end_marker = "\nPY\n"
    start = source.index(start_marker) + len(start_marker)
    end = source.rindex(end_marker)
    return source[start:end]


PROGRAM = _embedded_program()


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.read_limit: int | None = None

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.body


def connection_factory(
    *,
    response: FakeResponse | None = None,
    request_error: BaseException | None = None,
) -> type:
    class FakeConnection:
        instances: list[FakeConnection] = []

        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.requests: list[dict[str, Any]] = []
            self.closed = False
            self.response = response
            type(self).instances.append(self)

        def request(
            self,
            method: str,
            path: str,
            *,
            body: bytes,
            headers: dict[str, str],
        ) -> None:
            self.requests.append(
                {
                    "method": method,
                    "path": path,
                    "body": body,
                    "headers": headers,
                }
            )
            if request_error is not None:
                raise request_error

        def getresponse(self) -> FakeResponse:
            if self.response is None:
                raise AssertionError("fixture response was not configured")
            return self.response

        def close(self) -> None:
            self.closed = True

    return FakeConnection


def home_with_token(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    config = home / ".config"
    config.mkdir(parents=True)
    (config / "imcp-bridge.token").write_text(TOKEN + "\n", encoding="utf-8")
    return home


def run_program(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    connection_type: type,
) -> tuple[int, str, str]:
    monkeypatch.setenv("HOME", str(home))
    namespace = {"__name__": "__main__", "__file__": str(SCRIPT)}
    with patch.object(http.client, "HTTPConnection", connection_type):
        with pytest.raises(SystemExit) as raised:
            exec(compile(PROGRAM, str(SCRIPT), "exec"), namespace)
    captured = capsys.readouterr()
    return int(raised.value.code), captured.out, captured.err


def assert_no_sensitive_output(output: str) -> None:
    assert TOKEN not in output
    assert TOOL_METADATA not in output


@pytest.mark.parametrize("tools", [[], [{"name": TOOL_METADATA, "description": "private"}]])
def test_accepts_valid_and_empty_listings_without_printing_metadata(
    tools: list[Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = json.dumps(
        {"ok": True, "result": {"tools": tools}, "truncated": False}
    ).encode("utf-8")
    response = FakeResponse(200, body)
    connection_type = connection_factory(response=response)

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status == 0
    assert stdout.splitlines()[-1] == "bridge list_tools request completed successfully"
    assert "manual client approval" not in stdout
    assert stderr == ""
    assert_no_sensitive_output(stdout + stderr)
    connection = connection_type.instances[0]
    assert connection.host == "127.0.0.1"
    assert connection.port == 8766
    assert connection.timeout == 20
    assert connection.closed
    assert len(connection.requests) == 1
    request = connection.requests[0]
    assert request["method"] == "POST"
    assert request["path"] == "/bridge"
    assert request["body"] == b'{"operation":"list_tools"}'
    assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert request["headers"]["Content-Type"] == "application/json"


def test_auth_error_is_failure_without_body_or_token_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = FakeResponse(
        401,
        json.dumps(
            {
                "ok": False,
                "error": {"message": TOKEN, "metadata": TOOL_METADATA},
            }
        ).encode("utf-8"),
    )
    connection_type = connection_factory(response=response)

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status != 0
    assert "retry only this read-only listing" in stderr
    assert_no_sensitive_output(stdout + stderr)
    assert len(connection_type.instances) == 1
    assert len(connection_type.instances[0].requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not-json-with-sensitive-metadata",
        b'{"ok":true,"result":{"tools":"not-a-list"},"truncated":false}',
    ],
)
def test_malformed_response_is_failure_and_is_bounded(
    body: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = FakeResponse(200, body)
    connection_type = connection_factory(response=response)

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status != 0
    assert_no_sensitive_output(stdout + stderr)
    assert response.read_limit == 256 * 1024 + 1


def test_oversized_response_is_rejected_after_one_extra_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = FakeResponse(200, b"x" * (256 * 1024 + 1))
    connection_type = connection_factory(response=response)

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status != 0
    assert response.read_limit == 256 * 1024 + 1
    assert_no_sensitive_output(stdout + stderr)


def test_missing_token_does_not_contact_any_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    connection_type = connection_factory(
        response=FakeResponse(
            200,
            b'{"ok":true,"result":{"tools":[]},"truncated":false}',
        )
    )

    status, stdout, stderr = run_program(monkeypatch, capsys, home, connection_type)

    assert status != 0
    assert not connection_type.instances
    assert_no_sensitive_output(stdout + stderr)


def test_timeout_has_no_retry_and_no_sensitive_error_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection_type = connection_factory(
        request_error=TimeoutError(f"timed out while handling {TOKEN} {TOOL_METADATA}")
    )

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status != 0
    assert len(connection_type.instances) == 1
    assert len(connection_type.instances[0].requests) == 1
    assert connection_type.instances[0].closed
    assert_no_sensitive_output(stdout + stderr)


def test_redirect_is_not_followed_or_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = FakeResponse(
        302,
        b'{"ok":true,"result":{"tools":[]},"truncated":false}',
    )
    connection_type = connection_factory(response=response)

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status != 0
    assert len(connection_type.instances) == 1
    assert len(connection_type.instances[0].requests) == 1
    assert_no_sensitive_output(stdout + stderr)


def test_environment_proxies_are_ignored_by_direct_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(variable, "http://proxy.example.invalid:9")
    monkeypatch.setenv("NO_PROXY", "")
    response = FakeResponse(
        200,
        b'{"ok":true,"result":{"tools":[]},"truncated":false}',
    )
    connection_type = connection_factory(response=response)

    status, stdout, stderr = run_program(monkeypatch, capsys, home_with_token(tmp_path), connection_type)

    assert status == 0
    assert connection_type.instances[0].host == "127.0.0.1"
    assert connection_type.instances[0].port == 8766
    assert_no_sensitive_output(stdout + stderr)
