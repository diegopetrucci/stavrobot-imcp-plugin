"""Small, dependency-free HTTP client shared by the iMCP plugin tools."""

from __future__ import annotations

import json
import signal
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlsplit


# Leave the host bridge's 15-second outer deadline enough room to finish and
# return its structured response, while staying below the plugin runner's
# 30-second synchronous-tool kill limit.
BRIDGE_OUTER_DEADLINE_SECONDS = 15.0
RUNNER_KILL_LIMIT_SECONDS = 30.0
HTTP_TIMEOUT_SECONDS = 20.0
assert BRIDGE_OUTER_DEADLINE_SECONDS < HTTP_TIMEOUT_SECONDS < RUNNER_KILL_LIMIT_SECONDS
MAX_RESPONSE_BYTES = 256 * 1024
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
_REDACTED = "[REDACTED]"
_UNKNOWN_OUTCOME_MESSAGE = "call may have executed; do not retry"


class _InvalidConfiguration(Exception):
    """Internal marker; its text is never exposed."""


class _InvalidResponse(Exception):
    """Internal marker; its text is never exposed."""


class _ResponseTooLarge(Exception):
    """Internal marker for a response that cannot be safely decoded."""


class _HTTPDeadlineExpired(Exception):
    """Raised by the temporary process-wide wall-clock deadline."""


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Reject every redirect recognized by urllib without opening its target."""

    def redirect_request(
        self,
        req: urllib_request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del newurl
        raise urllib_error.HTTPError(req.full_url, code, msg, headers, fp)


# Keep this opener private to the plugin client rather than changing urllib's
# process-global opener.  An explicit empty proxy mapping prevents urllib from
# honoring proxy environment variables, while supplying a HTTPRedirectHandler
# subclass causes build_opener() to omit urllib's default redirect handler.
HTTP_OPENER = urllib_request.build_opener(
    urllib_request.ProxyHandler({}),
    _NoRedirectHandler(),
)


@contextmanager
def _http_deadline(timeout: float) -> Iterator[None]:
    """Bound one blocking HTTP operation with a restorable Unix wall timer.

    ``urllib``'s timeout is an inactivity/socket timeout rather than a total
    request deadline.  Plugin tools run on the process' main thread on the
    supported Linux/macOS runtimes, where SIGALRM/ITIMER_REAL interrupts both
    connect and read operations.  The previous handler and timer are restored
    in all paths so importing/calling the client does not leave process-global
    signal state changed.
    """

    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        raise RuntimeError("wall-clock deadline is unavailable")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("invalid HTTP deadline")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    state_changed = False

    def raise_deadline(_signum: int, _frame: Any) -> None:
        raise _HTTPDeadlineExpired

    try:
        signal.signal(signal.SIGALRM, raise_deadline)
        state_changed = True
        signal.setitimer(signal.ITIMER_REAL, float(timeout), 0.0)
        yield
    finally:
        if state_changed:
            elapsed = max(0.0, time.monotonic() - started)
            # Disable the temporary timer before restoring the old handler.
            # This prevents a late callback from invoking the wrong handler.
            signal.setitimer(signal.ITIMER_REAL, 0.0, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)

            previous_delay, previous_interval = previous_timer
            if previous_delay > 0 or previous_interval > 0:
                # Reinstall the old timer with the remaining delay.  A timer
                # that would have fired while the HTTP operation was active is
                # scheduled for its next due instant rather than silently
                # discarded.
                if elapsed < previous_delay:
                    remaining = previous_delay - elapsed
                elif previous_interval > 0:
                    overdue = elapsed - previous_delay
                    cycles = int(overdue // previous_interval) + 1
                    remaining = previous_delay + cycles * previous_interval - elapsed
                else:
                    remaining = 1e-6
                signal.setitimer(signal.ITIMER_REAL, max(1e-6, remaining), previous_interval)


def error_payload(code: str, message: str, *, truncated: bool = False) -> dict[str, Any]:
    """Build the fixed-shape error envelope used for local client failures."""

    return {
        "ok": False,
        "error": {"code": code, "message": message},
        "truncated": truncated,
    }


def unknown_outcome_payload() -> dict[str, Any]:
    """Return the non-retryable result for a call whose dispatch is uncertain."""

    return {
        "ok": False,
        "error": {
            "code": "unknown_outcome",
            "message": _UNKNOWN_OUTCOME_MESSAGE,
            "retryable": False,
        },
        "truncated": False,
    }


def load_config() -> tuple[str, str]:
    """Load and validate bridge configuration without exposing its values."""

    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
        config = json.loads(raw)
    except Exception as exc:
        del exc
        raise _InvalidConfiguration from None

    if not isinstance(config, dict):
        raise _InvalidConfiguration

    bridge_url = config.get("bridge_url")
    bridge_token = config.get("bridge_token")
    if not isinstance(bridge_url, str) or not bridge_url:
        raise _InvalidConfiguration
    if not isinstance(bridge_token, str) or not bridge_token:
        raise _InvalidConfiguration
    if any(character.isspace() for character in bridge_token):
        raise _InvalidConfiguration

    try:
        parsed = urlsplit(bridge_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _InvalidConfiguration
        # Credentials in the URL are not needed: bridge_token is the sole
        # credential and is sent in the Authorization header.
        if parsed.username is not None or parsed.password is not None or parsed.hostname is None:
            raise _InvalidConfiguration
    except (ValueError, UnicodeError):
        raise _InvalidConfiguration from None

    return bridge_url, bridge_token


def _redact(value: Any, secret: str) -> Any:
    """Remove the configured token from every string in a decoded response."""

    # Keep the replacement itself from containing an unusually chosen token
    # (for example, a token equal to part of ``[REDACTED]``).
    replacement = _REDACTED if secret not in _REDACTED else ""
    if isinstance(value, str):
        return value.replace(secret, replacement) if secret else value
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {
            _redact(key, secret) if isinstance(key, str) else key: _redact(item, secret)
            for key, item in value.items()
        }
    return value


def _parse_response(response: Any, token: str) -> dict[str, Any]:
    """Decode one bridge response while retaining its JSON structure."""

    try:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception as exc:
        del exc
        raise _InvalidResponse from None

    if not isinstance(body, (bytes, bytearray)):
        raise _InvalidResponse
    if len(body) > MAX_RESPONSE_BYTES:
        raise _ResponseTooLarge

    try:
        def reject_constant(_value: str) -> None:
            raise ValueError

        payload = json.loads(bytes(body).decode("utf-8"), parse_constant=reject_constant)
    except Exception as exc:
        del exc
        raise _InvalidResponse from None

    if not isinstance(payload, dict):
        raise _InvalidResponse

    # Do not unwrap or normalize the bridge envelope.  This keeps MCP errors,
    # structured results, and the bridge's explicit truncated flag intact.
    redacted = _redact(payload, token)
    if not isinstance(redacted, dict):  # pragma: no cover - _redact preserves mappings
        raise _InvalidResponse
    return redacted


def _is_call_tool(operation: Mapping[str, Any]) -> bool:
    try:
        return operation.get("operation") == "call_tool"
    except Exception:
        return False


def request_bridge(operation: Mapping[str, Any]) -> dict[str, Any]:
    """POST one bridge operation and return a safe JSON object.

    HTTP error responses are decoded just like successful responses so the
    bridge's structured MCP errors are preserved.  Once the opener starts,
    any redirect, timeout, reset, malformed/oversized response, or transport
    exception is conservatively unknown for ``call_tool`` and is never retried.
    """

    call_tool = _is_call_tool(operation)

    # Configuration is read and the request body is serialized before entering
    # the dispatch boundary.  These failures are known not to have dispatched.
    try:
        bridge_url, bridge_token = load_config()
    except Exception:
        return error_payload("configuration_error", "bridge configuration is unavailable")

    try:
        body = json.dumps(
            dict(operation),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception:
        return error_payload("serialization_error", "bridge request could not be serialized")

    try:
        http_request = urllib_request.Request(
            bridge_url,
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bridge_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
    except Exception:
        return error_payload("configuration_error", "bridge configuration is unavailable")

    dispatched = False
    try:
        with _http_deadline(HTTP_TIMEOUT_SECONDS):
            dispatched = True
            try:
                with HTTP_OPENER.open(http_request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    return _parse_response(response, bridge_token)
            except urllib_error.HTTPError as response:
                if 300 <= response.code < 400:
                    # Redirects are local transport failures, not bridge
                    # envelopes.  Close the origin response without exposing
                    # its Location header or any other exception text.
                    response.close()
                    return unknown_outcome_payload() if call_tool else error_payload(
                        "bridge_unavailable", "bridge request failed"
                    )
                # urllib raises HTTPError for 4xx/5xx, but the bridge body can
                # still contain a useful structured MCP error.  Decode it
                # without using the exception's URL, reason, or text.
                return _parse_response(response, bridge_token)
    except _HTTPDeadlineExpired:
        return unknown_outcome_payload() if call_tool and dispatched else error_payload(
            "bridge_unavailable", "bridge request failed"
        )
    except _ResponseTooLarge:
        if call_tool and dispatched:
            return unknown_outcome_payload()
        return error_payload(
            "response_too_large",
            "bridge response exceeded the client limit",
            truncated=True,
        )
    except _InvalidResponse:
        return unknown_outcome_payload() if call_tool and dispatched else error_payload(
            "invalid_response", "bridge returned invalid JSON"
        )
    except Exception:
        # Deliberately do not interpolate or log the exception.  urllib errors
        # may contain the configured URL, and lower layers may contain secrets.
        return unknown_outcome_payload() if call_tool and dispatched else error_payload(
            "bridge_unavailable", "bridge request failed"
        )


def write_json(payload: Mapping[str, Any]) -> None:
    """Write one valid JSON object without any diagnostic text."""

    import sys

    sys.stdout.write(
        json.dumps(
            dict(payload),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
    )
    sys.stdout.write("\n")
