"""Authenticated HTTP bridge for the host-local iMCP MCP session.

The HTTP side of the bridge is intentionally small and synchronous, while the
official MCP client session lives on one asyncio event loop.  A session is
opened on first use and retained until it is known to be unusable.  A failed
``tools/call`` is never replayed: after dispatch, a transport failure is
reported as an unknown outcome and the session is discarded for the *next*
request only.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hmac
import inspect
import json
import logging
import math
import threading
import time
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, TypeAlias
from urllib.parse import urlsplit

from mcp import MCPError, types

# Keep direct execution (``python bridge/server.py``) working without installing
# the repository as a package.
try:
    from stavrobot_imcp import open_imcp_session
except ModuleNotFoundError:  # pragma: no cover - only used for direct execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from stavrobot_imcp import open_imcp_session


LOGGER = logging.getLogger("imcp.bridge")
_BRIDGE_HANDLER_MARKER = "_imcp_bridge_handler"
_ROOT_SUPPRESSOR_MARKER = "_imcp_bridge_root_suppressor"


def _configure_logging() -> None:
    """Keep CLI output limited to sanitized bridge records.

    The bridge is the only logger that owns an output handler.  A root
    ``NullHandler`` also prevents third-party records from falling through to
    ``logging.lastResort`` when their logger emits at WARNING or above.
    """

    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

    bridge_handlers = [
        handler for handler in LOGGER.handlers if getattr(handler, _BRIDGE_HANDLER_MARKER, False)
    ]
    bridge_handler = bridge_handlers[0] if bridge_handlers else logging.StreamHandler()
    setattr(bridge_handler, _BRIDGE_HANDLER_MARKER, True)
    bridge_handler.setLevel(logging.INFO)
    bridge_handler.setFormatter(logging.Formatter("%(message)s"))
    if not bridge_handlers:
        LOGGER.addHandler(bridge_handler)
    for handler in list(LOGGER.handlers):
        if handler is not bridge_handler:
            LOGGER.removeHandler(handler)

    root = logging.getLogger()
    root_suppressors = [
        handler for handler in root.handlers if getattr(handler, _ROOT_SUPPRESSOR_MARKER, False)
    ]
    root_suppressor = root_suppressors[0] if root_suppressors else logging.NullHandler()
    setattr(root_suppressor, _ROOT_SUPPRESSOR_MARKER, True)
    root_suppressor.setLevel(logging.NOTSET)
    for handler in list(root.handlers):
        if handler is not root_suppressor:
            root.removeHandler(handler)
    if root_suppressor not in root.handlers:
        root.addHandler(root_suppressor)
    # A logger with propagate=False and no handlers bypasses the root logger,
    # so protect that fallback path too.  The bridge logger never propagates.
    logging.lastResort = root_suppressor


DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_PATH = "/bridge"
# The synchronous downstream plugin has a 20-second wall-clock ceiling.  Keep
# the default bridge deadline comfortably below it so timeout responses can be
# returned before the plugin has to synthesize its own failure.
DEFAULT_CALL_TIMEOUT = 10.0
DEFAULT_DISCOVERY_TIMEOUT = 3.0
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_SETUP_TIMEOUT = DEFAULT_DISCOVERY_TIMEOUT * 2 + DEFAULT_CONNECT_TIMEOUT
DEFAULT_RUNTIME_HEADROOM = 5.0
DEFAULT_RUNTIME_TIMEOUT = DEFAULT_CALL_TIMEOUT + DEFAULT_RUNTIME_HEADROOM
DEFAULT_CLOSE_TIMEOUT = 2.0
MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_TOOL_NAME_BYTES = 256
MAX_LIST_PAGES = 1024
HTTP_READ_TIMEOUT = 15.0

# The MCP SDK uses these JSON-RPC codes for transport failures.  A response
# carrying any other MCPError is a known server/protocol error and can be
# returned without replaying the request.
_TRANSPORT_ERROR_CODES = frozenset(
    {
        types.CONNECTION_CLOSED,
        types.REQUEST_TIMEOUT,
    }
)

SessionFactory: TypeAlias = Callable[[], Any]


class BridgeConfigurationError(ValueError):
    """Raised when trusted bridge configuration is invalid."""


class SessionUnavailableError(RuntimeError):
    """Raised internally when a new MCP session could not be established."""

    def __init__(self, *, app_reachable: bool) -> None:
        super().__init__("MCP session unavailable")
        self.app_reachable = app_reachable


@dataclass(frozen=True, slots=True)
class OperationResponse:
    """A sanitized operation result ready for the HTTP layer."""

    payload: dict[str, Any]
    status_code: int = HTTPStatus.OK
    tool_name: str = "bridge"
    log_status: str = "ok"


@dataclass(frozen=True, slots=True)
class _HTTPFailure(Exception):
    status_code: int
    code: str
    message: str


class _SessionOnlyContext:
    """Adapt a directly supplied fake session to the context-manager contract."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        close = getattr(self.session, "aclose", None)
        if not callable(close):
            close = getattr(self.session, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


def _positive_timeout(value: float, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeConfigurationError(f"{label} must be a finite positive number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0:
        raise BridgeConfigurationError(f"{label} must be a finite positive number")
    return converted


def _consume_task_result(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        with suppress(BaseException):
            task.exception()


class _SessionOwner:
    """Keep one MCP context's entry and exit in the same asyncio task."""

    def __init__(self, context: Any, *, close_timeout: float) -> None:
        self.context = context
        self.close_timeout = close_timeout
        self.loop = asyncio.get_running_loop()
        self.ready: asyncio.Future[Any] = self.loop.create_future()
        self.ready.add_done_callback(_consume_task_result)
        self.stop_event = asyncio.Event()
        self.task: asyncio.Task[Any] | None = None
        self.session: Any | None = None
        self.entered = False
        self.exit_error: BaseException | None = None

    def start(self) -> None:
        if self.task is not None:
            raise RuntimeError("session owner already started")
        self.task = asyncio.create_task(self._run(), name="imcp-session-owner")
        self.task.add_done_callback(_consume_task_result)

    async def wait_ready(self, timeout: float) -> Any:
        self.start()
        try:
            return await _await_bounded(asyncio.shield(self.ready), timeout)
        except BaseException:
            await self.close(cancel=True)
            raise

    async def _run(self) -> None:
        entered = False
        try:
            self.session = await self.context.__aenter__()
            entered = True
            self.entered = True
            if not self.ready.done():
                self.ready.set_result(self.session)
            await self.stop_event.wait()
        except BaseException as exc:
            if not self.ready.done():
                if isinstance(exc, asyncio.CancelledError):
                    self.ready.cancel()
                else:
                    self.ready.set_exception(exc)
            raise
        finally:
            if entered:
                exit_method = getattr(self.context, "__aexit__", None)
                if callable(exit_method):
                    try:
                        await exit_method(None, None, None)
                    except BaseException as exc:
                        # Cleanup must not become an unhandled task exception.  The
                        # owner records it for regression tests and still retires.
                        self.exit_error = exc

    async def close(self, *, cancel: bool = False) -> None:
        task = self.task
        if task is None:
            return
        self.stop_event.set()
        if cancel and not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), self.close_timeout)
        except asyncio.TimeoutError:
            if not task.done():
                task.cancel()
                task.add_done_callback(_consume_task_result)
        except asyncio.CancelledError:
            # A cancellation raised by the owner itself is cleanup completion;
            # a cancellation of this caller is propagated after detaching it.
            if task.cancelled():
                return
            if not task.done():
                task.cancel()
                task.add_done_callback(_consume_task_result)
            raise
        except BaseException:
            # Context teardown is best effort and bounded; never leak lower
            # layer exception details through the bridge.
            _consume_task_result(task)


async def _await_bounded(awaitable: Any, timeout: float) -> Any:
    """Await an operation without waiting on cancellation handlers past its bound."""

    task = asyncio.ensure_future(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=timeout)
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume_task_result)
        raise
    if not done:
        task.cancel()
        task.add_done_callback(_consume_task_result)
        raise asyncio.TimeoutError
    return task.result()


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise BridgeConfigurationError("path must be a non-empty absolute URL path")
    normalized = value if value.startswith("/") else f"/{value}"
    if "?" in normalized or "#" in normalized or "\x00" in normalized:
        raise BridgeConfigurationError("path must not contain a query, fragment, or null byte")
    if len(normalized) > 256:
        raise BridgeConfigurationError("path is too long")
    return normalized.rstrip("/") or "/"


def _validate_tool_name(name: Any) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    if "\x00" in name:
        raise ValueError("name contains a null byte")
    if len(name.encode("utf-8")) > MAX_TOOL_NAME_BYTES:
        raise ValueError("name is too long")
    return name


def _json_loads(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)


def _json_value(value: Any) -> Any:
    """Convert SDK models to JSON without stringifying structured content."""

    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_value(value.model_dump(by_alias=True, mode="json", exclude_none=False))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _error_payload(
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error.update(details)
    return {"ok": False, "error": error, "truncated": False}


def _success_payload(result: Any) -> dict[str, Any]:
    return {"ok": True, "result": _json_value(result), "truncated": False}


def _mcp_error_payload(error: MCPError) -> dict[str, Any]:
    # Preserve the SDK's JSON-RPC error fields.  In particular, ``data`` is
    # kept structured instead of being folded into the exception's string.
    return {
        "ok": False,
        "error": {
            "kind": "mcp",
            "code": error.code,
            "message": error.message,
            "data": _json_value(error.data),
        },
        "truncated": False,
    }


def _unknown_outcome_payload() -> dict[str, Any]:
    return _error_payload(
        "unknown_outcome",
        "tool call outcome is unknown; the call was not retried",
        details={"retryable": False},
    )


def _safe_log_tool_name(value: str) -> str:
    """Keep the required tool-name field bounded and single-line."""

    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in value)
    return safe[:MAX_TOOL_NAME_BYTES] or "unknown"


def _dump_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except UnicodeEncodeError:
        # JSON may contain an escaped lone surrogate from an upstream model;
        # ASCII escaping keeps the response valid without stringifying it.
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")


def _ordered_mapping_items(value: Mapping[Any, Any]) -> list[tuple[Any, Any]]:
    """Put MCP result metadata before potentially unbounded content."""

    priority = (
        "isError",
        "structuredContent",
        "resultType",
        "_meta",
        "content",
        # Accept SDK-style Python names in test/fake mappings too.
        "structured_content",
        "is_error",
    )
    positions = {name: index for index, name in enumerate(priority)}
    return sorted(value.items(), key=lambda item: positions.get(item[0], len(priority)))


def _bounded_json_value(value: Any, budget: int) -> tuple[Any | None, bytes | None]:
    """Build one valid JSON value in one bounded traversal.

    The returned bytes are assembled as the tree is visited, so callers never
    repeatedly dump the growing prefix.  Strings are copied character by
    character to respect UTF-8/JSON escaping; arrays and objects stop before
    their byte budget and retain their original JSON shape.
    """

    if budget <= 0:
        return None, None

    if isinstance(value, str):
        encoded = _dump_json(value)
        if len(encoded) <= budget:
            return value, encoded
        if budget < 2:
            return None, None
        characters: list[str] = []
        used = 2  # quotes
        for character in value:
            fragment = _dump_json(character)[1:-1]
            fragment_size = len(fragment)
            if used + fragment_size > budget:
                break
            characters.append(character)
            used += fragment_size
        compacted = "".join(characters)
        return compacted, _dump_json(compacted)

    if value is None or isinstance(value, (bool, int, float)):
        try:
            encoded = _dump_json(value)
        except (TypeError, ValueError):
            return None, None
        return (value, encoded) if len(encoded) <= budget else (None, None)

    if isinstance(value, Mapping):
        if budget < 2:
            return None, None
        pairs: list[bytes] = []
        compacted: dict[str, Any] = {}
        used = 1  # opening brace
        for raw_key, raw_value in _ordered_mapping_items(value):
            key = raw_key if isinstance(raw_key, str) else str(raw_key)
            try:
                encoded_key = _dump_json(key)
            except (TypeError, ValueError):
                continue
            separator_size = 1 if pairs else 0
            child_budget = budget - used - separator_size - len(encoded_key) - 2
            # One byte for ':' and one for the closing brace are reserved.
            if child_budget <= 0:
                continue
            child, encoded_child = _bounded_json_value(raw_value, child_budget)
            if encoded_child is None:
                continue
            pair = encoded_key + b":" + encoded_child
            if used + separator_size + len(pair) + 1 > budget:
                continue
            pairs.append(pair)
            compacted[key] = child
            used += separator_size + len(pair)
        encoded = b"{" + b",".join(pairs) + b"}"
        return compacted, encoded

    if isinstance(value, (list, tuple)):
        if budget < 2:
            return None, None
        items: list[Any] = []
        encoded_items: list[bytes] = []
        used = 1  # opening bracket
        for raw_item in value:
            separator_size = 1 if encoded_items else 0
            child_budget = budget - used - separator_size - 1  # closing bracket
            if child_budget <= 0:
                break
            child, encoded_child = _bounded_json_value(raw_item, child_budget)
            if encoded_child is None:
                break
            if used + separator_size + len(encoded_child) + 1 > budget:
                break
            items.append(child)
            encoded_items.append(encoded_child)
            used += separator_size + len(encoded_child)
        encoded = b"[" + b",".join(encoded_items) + b"]"
        return items, encoded

    return None, None


def _encode_json(payload: Mapping[str, Any], *, limit: int = MAX_RESPONSE_BYTES) -> tuple[bytes, bool]:
    """Encode a response under the byte limit while retaining result semantics.

    Normal responses are emitted unchanged.  For an oversized MCP result the
    ``truncated`` flag is set and a single bounded traversal prunes values.  A
    result mapping gives priority to ``isError`` and ``structuredContent`` over
    ``content`` so a large leading content array cannot hide semantic fields.
    """

    original = dict(payload)
    try:
        encoded = _dump_json(original)
    except (TypeError, ValueError):
        encoded = b""
    if len(encoded) <= limit and encoded:
        return encoded, False

    truncated: dict[str, Any] = dict(original)
    truncated["truncated"] = True
    nested_key = "result" if "result" in truncated else "error" if "error" in truncated else None
    if nested_key is not None:
        # Calculate the exact envelope overhead by replacing the nested value
        # with JSON null.  The nested replacement can therefore use every
        # remaining byte without a guessed reserve.
        envelope = dict(truncated)
        envelope[nested_key] = None
        try:
            overhead = len(_dump_json(envelope)) - len(b"null")
        except (TypeError, ValueError):
            overhead = limit
        nested_budget = max(0, limit - overhead)
        compacted, _nested_bytes = _bounded_json_value(truncated[nested_key], nested_budget)
        truncated[nested_key] = compacted if compacted is not None else {}

    try:
        encoded = _dump_json(truncated)
    except (TypeError, ValueError):
        encoded = b""
    if len(encoded) <= limit and encoded:
        return encoded, True

    # A maliciously large top-level key or unsupported value can leave no room
    # for a useful nested value.  Return a small structured response instead of
    # cutting JSON at an arbitrary byte boundary.
    fallback = {
        "ok": False,
        "error": {
            "code": "response_too_large",
            "message": "response exceeded the configured size limit",
        },
        "truncated": True,
    }
    encoded = _dump_json(fallback)
    if len(encoded) > limit:  # pragma: no cover - constants make this unreachable
        raise RuntimeError("response size limit is too small for the error envelope")
    return encoded, True


def load_token(path: Path) -> str:
    """Read a bearer token once from trusted startup configuration."""

    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise BridgeConfigurationError("token file could not be read") from exc
    if not token or any(character.isspace() for character in token):
        raise BridgeConfigurationError("token file is empty or contains whitespace")
    return token


def _allowlist_entries(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        values: Iterable[Any] = (value,)
    elif isinstance(value, list):
        values = value
    elif isinstance(value, Mapping):
        configured = value.get("tools", value.get("allowlist"))
        if isinstance(configured, str):
            values = (configured,)
        elif isinstance(configured, list):
            values = configured
        else:
            raise BridgeConfigurationError("allowlist config must contain a tools list")
    else:
        raise BridgeConfigurationError("allowlist config must be a list of tool names")

    entries: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item:
            raise BridgeConfigurationError("allowlist entries must be non-empty strings")
        if item != "*":
            try:
                _validate_tool_name(item)
            except ValueError as exc:
                raise BridgeConfigurationError("allowlist entries must be valid tool names") from exc
        entries.add(item)
    return frozenset(entries)


def load_allowlist(path: Path | None) -> frozenset[str]:
    """Load the trusted JSON allowlist; an omitted file permits ``*``."""

    if path is None:
        return frozenset({"*"})
    try:
        raw = path.read_bytes()
        value = _json_loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise BridgeConfigurationError("allowlist file could not be read as JSON") from exc
    return _allowlist_entries(value)


class BridgeService:
    """Own one persistent MCP session and expose the bridge operations."""

    def __init__(
        self,
        *,
        token: str | None = None,
        allowlist: Iterable[str] = ("*",),
        session_factory: SessionFactory | None = None,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        setup_timeout: float | None = None,
        close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    ) -> None:
        # ``token`` is accepted for callers that keep auth and service config
        # together, but authentication is enforced by the HTTP handler.  Do
        # not retain or log it in the service.
        del token
        entries = frozenset(allowlist)
        if any(not isinstance(item, str) or not item for item in entries):
            raise BridgeConfigurationError("allowlist entries must be non-empty strings")
        for item in entries:
            if item != "*":
                try:
                    _validate_tool_name(item)
                except ValueError as exc:
                    raise BridgeConfigurationError("allowlist entries must be valid tool names") from exc
        self._allowlist = entries
        self._call_timeout = _positive_timeout(call_timeout, label="call timeout")
        self._discovery_timeout = _positive_timeout(discovery_timeout, label="discovery timeout")
        self._connect_timeout = _positive_timeout(connect_timeout, label="connect timeout")
        derived_setup_timeout = self._discovery_timeout * 2 + self._connect_timeout
        self._setup_timeout = _positive_timeout(
            derived_setup_timeout if setup_timeout is None else setup_timeout,
            label="setup timeout",
        )
        self._close_timeout = _positive_timeout(close_timeout, label="close timeout")
        self._session_factory = session_factory or self._default_session_factory

        self._lock = asyncio.Lock()
        self._session_owner: _SessionOwner | None = None
        self._session: Any | None = None
        self._session_known_dead = False
        # None means no connection attempt has produced app reachability
        # evidence yet; subsequent attempts settle this to True or False.
        self._last_app_reachable: bool | None = None

    def _default_session_factory(self) -> Any:
        # Every invocation creates a new shared-transport context.  The
        # context performs a fresh Bonjour port discovery before connecting to
        # the forced IPv4 loopback endpoint, including after reconnects.
        return open_imcp_session(
            client_info=types.Implementation(
                name="stavrobot-imcp-bridge",
                version="1.0.0",
            ),
            read_timeout_seconds=self._call_timeout,
            discovery_timeout=self._discovery_timeout,
            connect_timeout=self._connect_timeout,
            close_timeout=self._close_timeout,
        )

    @property
    def session_up(self) -> bool:
        return self._session is not None and not self._session_known_dead

    @property
    def app_reachable(self) -> bool | None:
        return self._last_app_reachable

    def allows(self, name: str) -> bool:
        return "*" in self._allowlist or name in self._allowlist

    async def _close_session_locked(self) -> None:
        owner = self._session_owner
        self._session_owner = None
        self._session = None
        if owner is None:
            return
        with suppress(BaseException):
            await owner.close()

    @staticmethod
    def _bounded_phase_timeout(configured: float, deadline: float | None) -> float:
        """Limit one phase to the remaining outer request deadline."""

        if deadline is None:
            return configured
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        return min(configured, remaining)

    async def _ensure_session_locked(self, *, deadline: float | None = None) -> Any:
        if self._session is not None and not self._session_known_dead:
            return self._session

        # A known-dead session is retired before this new request is
        # dispatched.  This is the only reconnect point in the bridge.
        await self._close_session_locked()
        self._session_known_dead = False

        try:
            candidate = self._session_factory()
            if inspect.isawaitable(candidate):
                try:
                    setup_timeout = self._bounded_phase_timeout(self._setup_timeout, deadline)
                except asyncio.TimeoutError:
                    if isinstance(candidate, asyncio.Future):
                        candidate.cancel()
                    elif inspect.iscoroutine(candidate):
                        candidate.close()
                    raise
                candidate = await _await_bounded(candidate, setup_timeout)
            context = candidate if callable(getattr(candidate, "__aenter__", None)) else _SessionOnlyContext(candidate)
            owner = _SessionOwner(context, close_timeout=self._close_timeout)
            self._session_owner = owner
        except asyncio.CancelledError:
            raise
        except Exception:
            self._last_app_reachable = False
            raise SessionUnavailableError(app_reachable=False) from None

        try:
            # ``open_imcp_session().__aenter__`` includes Bonjour observation,
            # service-detail resolution, and TCP connect.  Its bound must
            # cover all three phases rather than using connect_timeout alone.
            setup_timeout = self._bounded_phase_timeout(self._setup_timeout, deadline)
            session = await owner.wait_ready(setup_timeout)
            self._session = session
            self._last_app_reachable = True
            initialize_timeout = self._bounded_phase_timeout(self._call_timeout, deadline)
            await _await_bounded(session.initialize(), initialize_timeout)
            return session
        except asyncio.CancelledError:
            self._last_app_reachable = owner.entered
            await self._close_session_locked()
            raise
        except Exception:
            self._last_app_reachable = owner.entered
            await self._close_session_locked()
            raise SessionUnavailableError(app_reachable=owner.entered) from None

    async def _mark_session_dead_locked(self) -> None:
        self._session_known_dead = True
        self._last_app_reachable = False
        await self._close_session_locked()

    async def mark_session_dead(self) -> None:
        """Mark the persistent session dead for deterministic tests/shutdown."""

        async with self._lock:
            await self._mark_session_dead_locked()

    def _unavailable_response(self, *, tool_name: str, app_reachable: bool | None) -> OperationResponse:
        return OperationResponse(
            _error_payload(
                "mcp_unavailable",
                "MCP session unavailable",
                details={"app_reachable": app_reachable},
            ),
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            tool_name=tool_name,
            log_status="unavailable",
        )

    def _mcp_error_response(self, error: MCPError, *, tool_name: str) -> OperationResponse:
        return OperationResponse(
            _mcp_error_payload(error),
            status_code=HTTPStatus.BAD_GATEWAY,
            tool_name=tool_name,
            log_status="mcp_error",
        )

    async def _health(self) -> OperationResponse:
        # All state is owned by the runtime event loop.  Do not acquire the
        # operation lock here: health must remain responsive while an MCP call
        # is in flight.
        session_up = self._session is not None and not self._session_known_dead
        result = {
            "bridge_up": True,
            "mcp_session_up": session_up,
            "imcp_app_reachable": self._last_app_reachable,
        }
        return OperationResponse(_success_payload(result), tool_name="health")

    @staticmethod
    async def _call_tool_method(session: Any, name: str, arguments: dict[str, Any], timeout: float) -> Any:
        method = session.call_tool
        # Official ClientSession supports read_timeout_seconds.  Signature
        # inspection keeps small test fakes convenient without adding a second
        # invocation (which would violate the no-replay boundary).
        try:
            parameters = inspect.signature(method).parameters.values()
            accepts_timeout = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters) or any(
                parameter.name == "read_timeout_seconds" for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_timeout = True
        if accepts_timeout:
            result = method(name, arguments, read_timeout_seconds=timeout)
        else:
            result = method(name, arguments)
        return await _await_bounded(result, timeout)

    async def _call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> OperationResponse:
        async with self._lock:
            try:
                session = await self._ensure_session_locked(deadline=deadline)
            except SessionUnavailableError as exc:
                return self._unavailable_response(tool_name=name, app_reachable=exc.app_reachable)
            except asyncio.CancelledError:
                raise
            except Exception:
                return self._unavailable_response(tool_name=name, app_reachable=False)

            try:
                result = await self._call_tool_method(
                    session,
                    name,
                    arguments,
                    self._bounded_phase_timeout(self._call_timeout, deadline),
                )
            except MCPError as exc:
                if exc.code in _TRANSPORT_ERROR_CODES:
                    await self._mark_session_dead_locked()
                    return OperationResponse(
                        _unknown_outcome_payload(),
                        status_code=HTTPStatus.BAD_GATEWAY,
                        tool_name=name,
                        log_status="unknown_outcome",
                    )
                try:
                    return self._mcp_error_response(exc, tool_name=name)
                except Exception:
                    # A protocol error's structured data is also a response
                    # serialization boundary.  Retire the session rather than
                    # risk replaying a dispatched call.
                    await self._mark_session_dead_locked()
                    return OperationResponse(
                        _unknown_outcome_payload(),
                        status_code=HTTPStatus.BAD_GATEWAY,
                        tool_name=name,
                        log_status="unknown_outcome",
                    )
            except asyncio.CancelledError:
                await self._mark_session_dead_locked()
                raise
            except Exception:
                # Any exception after call_tool was entered is conservatively
                # treated as possibly dispatched.  Never reconnect and replay
                # from this branch.
                await self._mark_session_dead_locked()
                return OperationResponse(
                    _unknown_outcome_payload(),
                    status_code=HTTPStatus.BAD_GATEWAY,
                    tool_name=name,
                    log_status="unknown_outcome",
                )

            try:
                # Keep conversion and envelope construction in the same
                # boundary: deep SDK results can raise RecursionError, and a
                # failure here has the same unknown-outcome semantics as a
                # transport failure after dispatch.
                dumped = _json_value(result)
                is_tool_error = bool(getattr(result, "is_error", False))
                payload = {"ok": True, "result": dumped, "truncated": False}
            except Exception:
                # Do not narrow this to TypeError/ValueError.  RecursionError
                # and other runtime failures must retire the session too.
                await self._mark_session_dead_locked()
                return OperationResponse(
                    _unknown_outcome_payload(),
                    status_code=HTTPStatus.BAD_GATEWAY,
                    tool_name=name,
                    log_status="unknown_outcome",
                )
            return OperationResponse(
                payload,
                tool_name=name,
                log_status="mcp_tool_error" if is_tool_error else "ok",
            )

    @staticmethod
    def _page_tools(page: Any) -> tuple[list[Any], str | None]:
        if isinstance(page, Mapping):
            raw_tools = page.get("tools", [])
            cursor = page.get("nextCursor", page.get("next_cursor"))
        else:
            raw_tools = getattr(page, "tools", [])
            cursor = getattr(page, "next_cursor", None)
        if not isinstance(raw_tools, list):
            raise ValueError("invalid tools/list result")
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError("invalid tools/list cursor")
        return raw_tools, cursor

    async def _list_tools(self, *, deadline: float | None = None) -> OperationResponse:
        async with self._lock:
            try:
                session = await self._ensure_session_locked(deadline=deadline)
            except SessionUnavailableError as exc:
                return self._unavailable_response(tool_name="list_tools", app_reachable=exc.app_reachable)
            except asyncio.CancelledError:
                raise
            except Exception:
                return self._unavailable_response(tool_name="list_tools", app_reachable=False)

            tools: list[Any] = []
            cursor: str | None = None
            seen: set[str] = set()
            operation_deadline = asyncio.get_running_loop().time() + self._call_timeout
            if deadline is not None:
                operation_deadline = min(operation_deadline, deadline)
            try:
                for _ in range(MAX_LIST_PAGES):
                    remaining = operation_deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    params = types.PaginatedRequestParams(cursor=cursor) if cursor is not None else None
                    page = await _await_bounded(
                        session.list_tools(params=params),
                        remaining,
                    )
                    page_tools, cursor = self._page_tools(page)
                    for tool in page_tools:
                        tool_name = getattr(tool, "name", None)
                        if isinstance(tool, Mapping):
                            tool_name = tool.get("name")
                        if isinstance(tool_name, str) and self.allows(tool_name):
                            tools.append(_json_value(tool))
                    if cursor is None:
                        return OperationResponse(
                            _success_payload({"tools": tools}),
                            tool_name="list_tools",
                        )
                    if cursor in seen:
                        return OperationResponse(
                            _error_payload("invalid_mcp_response", "repeated tools/list cursor"),
                            status_code=HTTPStatus.BAD_GATEWAY,
                            tool_name="list_tools",
                            log_status="error",
                        )
                    seen.add(cursor)
            except MCPError as exc:
                if exc.code in _TRANSPORT_ERROR_CODES:
                    await self._mark_session_dead_locked()
                    return OperationResponse(
                        _unknown_outcome_payload(),
                        status_code=HTTPStatus.BAD_GATEWAY,
                        tool_name="list_tools",
                        log_status="unknown_outcome",
                    )
                return self._mcp_error_response(exc, tool_name="list_tools")
            except asyncio.CancelledError:
                await self._mark_session_dead_locked()
                raise
            except Exception:
                await self._mark_session_dead_locked()
                return OperationResponse(
                    _unknown_outcome_payload(),
                    status_code=HTTPStatus.BAD_GATEWAY,
                    tool_name="list_tools",
                    log_status="unknown_outcome",
                )

            return OperationResponse(
                _error_payload("invalid_mcp_response", "tools/list returned too many pages"),
                status_code=HTTPStatus.BAD_GATEWAY,
                tool_name="list_tools",
                log_status="error",
            )

    async def execute(
        self,
        request: Mapping[str, Any],
        *,
        deadline: float | None = None,
    ) -> OperationResponse:
        """Validate and execute one already-authenticated bridge request.

        ``deadline`` is the HTTP request's outer runtime deadline.  Setup,
        initialization, and MCP dispatch each receive the smaller of their
        phase bound and the remaining deadline so a cold request cannot run
        past the HTTP boundary.
        """

        operation = request.get("operation")
        if not isinstance(operation, str):
            return OperationResponse(
                _error_payload("invalid_request", "operation must be a string"),
                status_code=HTTPStatus.BAD_REQUEST,
                tool_name="bridge",
                log_status="error",
            )
        if operation == "health":
            return await self._health()
        if operation == "list_tools":
            return await self._list_tools(deadline=deadline)
        if operation != "call_tool":
            return OperationResponse(
                _error_payload("invalid_request", "unknown operation"),
                status_code=HTTPStatus.BAD_REQUEST,
                tool_name="bridge",
                log_status="error",
            )

        try:
            name = _validate_tool_name(request.get("name"))
        except ValueError as exc:
            return OperationResponse(
                _error_payload("invalid_request", str(exc)),
                status_code=HTTPStatus.BAD_REQUEST,
                tool_name="bridge",
                log_status="error",
            )
        arguments = request.get("arguments", {})
        if not isinstance(arguments, dict):
            return OperationResponse(
                _error_payload("invalid_request", "arguments must be a JSON object"),
                status_code=HTTPStatus.BAD_REQUEST,
                tool_name=name,
                log_status="error",
            )
        if not self.allows(name):
            return OperationResponse(
                _error_payload("tool_not_allowed", "tool is not allowlisted"),
                status_code=HTTPStatus.FORBIDDEN,
                tool_name=name,
                log_status="rejected",
            )
        return await self._call_tool(name, arguments, deadline=deadline)

    async def close(self) -> None:
        async with self._lock:
            await self._close_session_locked()
            self._session_known_dead = True
            self._last_app_reachable = False


class AsyncBridgeRuntime:
    """Run a :class:`BridgeService` on one thread-owned asyncio loop."""

    def __init__(self, service: BridgeService) -> None:
        self.service = service
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="imcp-bridge-async", daemon=True)
        self._state_lock = threading.RLock()
        self._ready = threading.Event()
        self._closed_event = threading.Event()
        self._started = False
        self._closed = False
        self._closing_thread: threading.Thread | None = None

    async def _drain_pending(self, pending: set[asyncio.Task[Any]]) -> None:
        for task in pending:
            task.cancel()
        # A user coroutine can ignore cancellation.  Do not let one such task
        # keep the runtime thread alive indefinitely during loop teardown.
        await asyncio.wait(pending, timeout=self.service._close_timeout)

    def _run(self) -> None:
        try:
            asyncio.set_event_loop(self.loop)
            self._ready.set()
            self.loop.run_forever()
        except BaseException:
            # Release start/close waiters even if loop setup itself fails. The
            # caller cannot safely use a loop that failed to start.
            self._ready.set()
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                if pending and not self.loop.is_closed():
                    self.loop.run_until_complete(self._drain_pending(pending))
                    for task in pending:
                        if not task.done():
                            # Avoid noisy destruction warnings for deliberately
                            # detached tasks whose cancellation handler ignored
                            # the teardown bound.
                            setattr(task, "_log_destroy_pending", False)
            except BaseException:
                pass
            finally:
                if not self.loop.is_closed():
                    self.loop.close()
                self._closed_event.set()

    @staticmethod
    def _discard_awaitable(awaitable: Any) -> None:
        if inspect.iscoroutine(awaitable):
            awaitable.close()

    def start(self) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("bridge runtime is closed")
            if not self._started:
                self._started = True
                try:
                    self._thread.start()
                except BaseException:
                    self._closed = True
                    if not self.loop.is_closed():
                        self.loop.close()
                    self._closed_event.set()
                    raise
        self._ready.wait()
        if not self._thread.is_alive() and not self.loop.is_running():
            raise RuntimeError("bridge runtime failed to start")

    def run(self, awaitable: Any, *, timeout: float) -> OperationResponse:
        try:
            self.start()
        except BaseException:
            self._discard_awaitable(awaitable)
            raise
        with self._state_lock:
            if self._closed or self.loop.is_closed() or not self._thread.is_alive():
                self._discard_awaitable(awaitable)
                raise RuntimeError("bridge runtime is closed")
            try:
                future = asyncio.run_coroutine_threadsafe(awaitable, self.loop)
            except BaseException:
                self._discard_awaitable(awaitable)
                raise
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # Cancellation is deliberately not awaited here: the service's
            # call boundary marks a possible dispatch unknown and the close
            # path has its own bound.
            future.cancel()
            raise

    async def _shutdown_service(self) -> None:
        await self.service.close()

    def close(self) -> None:
        current = threading.current_thread()
        with self._state_lock:
            if self._closed:
                if self._closing_thread is current:
                    return
                wait_for_close = True
            else:
                self._closed = True
                self._closing_thread = current
                wait_for_close = False
                started = self._started

        if wait_for_close:
            self._closed_event.wait(timeout=self.service._close_timeout + 2.0)
            return

        if not started:
            # No worker owns the loop, so close it here. This handles the
            # immediate-constructor-close path without leaking an event loop.
            if not self.loop.is_closed():
                self.loop.close()
            self._closed_event.set()
            return

        self._ready.wait()
        if current is self._thread:
            if self.loop.is_running():
                task = self.loop.create_task(self._shutdown_service())
                task.add_done_callback(lambda _task: self.loop.call_soon(self.loop.stop))
            return

        shutdown_coroutine = self._shutdown_service()
        future: concurrent.futures.Future[Any] | None = None
        try:
            future = asyncio.run_coroutine_threadsafe(shutdown_coroutine, self.loop)
            future.result(timeout=self.service._close_timeout + 1.0)
        except BaseException:
            if future is not None:
                with suppress(BaseException):
                    future.cancel()
            else:
                self._discard_awaitable(shutdown_coroutine)
            if self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
        finally:
            if self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=self.service._close_timeout + 1.0)
            if not self._thread.is_alive():
                self._closed_event.set()


class BridgeHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying only trusted startup configuration."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        *,
        token: str,
        bridge_path: str = DEFAULT_PATH,
        runtime: AsyncBridgeRuntime,
        runtime_timeout: float | None = None,
    ) -> None:
        self.bridge_token = token
        self.bridge_path = _normalize_path(bridge_path)
        self.runtime = runtime
        configured_runtime_timeout = (
            runtime.service._call_timeout + DEFAULT_RUNTIME_HEADROOM
            if runtime_timeout is None
            else runtime_timeout
        )
        self.runtime_timeout = _positive_timeout(configured_runtime_timeout, label="runtime timeout")
        super().__init__(server_address, request_handler)

    def handle_error(self, _request: Any, _client_address: Any) -> None:
        """Suppress socketserver's unsanitized exception traceback output."""

        return None


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Bearer-authenticated JSON HTTP request handler."""

    server: BridgeHTTPServer
    protocol_version = "HTTP/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(HTTP_READ_TIMEOUT)

    def log_message(self, _format: str, *_args: Any) -> None:
        # The standard handler would log request paths and headers.  Bridge
        # logs intentionally contain only tool, status, and duration.
        return None

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization")
        if not supplied:
            return False
        scheme, separator, value = supplied.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not value:
            return False
        return hmac.compare_digest(value.encode("utf-8"), self.server.bridge_token.encode("utf-8"))

    def _read_request(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding"):
            raise _HTTPFailure(
                HTTPStatus.LENGTH_REQUIRED,
                "invalid_request",
                "chunked request bodies are not supported",
            )
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise _HTTPFailure(HTTPStatus.LENGTH_REQUIRED, "invalid_request", "content length is required")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise _HTTPFailure(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid content length") from exc
        if length < 0:
            raise _HTTPFailure(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid content length")
        if length > MAX_REQUEST_BODY_BYTES:
            raise _HTTPFailure(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "request body is too large")
        body = self.rfile.read(length)
        if len(body) != length:
            raise _HTTPFailure(HTTPStatus.BAD_REQUEST, "invalid_request", "request body was incomplete")
        if not body:
            raise _HTTPFailure(HTTPStatus.BAD_REQUEST, "invalid_request", "request body is required")
        try:
            request = _json_loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise _HTTPFailure(HTTPStatus.BAD_REQUEST, "invalid_request", "request body is not valid JSON") from exc
        if not isinstance(request, dict):
            raise _HTTPFailure(HTTPStatus.BAD_REQUEST, "invalid_request", "request body must be a JSON object")
        return request

    def _write_payload(self, payload: Mapping[str, Any], status_code: int) -> None:
        try:
            body, _truncated = _encode_json(payload)
        except (TypeError, ValueError, RuntimeError):
            body, _truncated = _encode_json(
                _error_payload("internal_error", "bridge could not encode the response")
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _log_result(self, tool_name: str, status: str, started: float) -> None:
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        LOGGER.info(
            "tool=%s status=%s duration_ms=%d",
            _safe_log_tool_name(tool_name),
            status,
            duration_ms,
        )

    def _handle(self, request: Mapping[str, Any] | None) -> None:
        started = time.monotonic()
        tool_name = "bridge"
        status = "error"
        response_status = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            if not self._authorized():
                raise _HTTPFailure(HTTPStatus.UNAUTHORIZED, "unauthorized", "authentication required")
            if urlsplit(self.path).path != self.server.bridge_path:
                raise _HTTPFailure(HTTPStatus.NOT_FOUND, "not_found", "bridge path not found")
            if request is None:
                request = self._read_request()
            operation = request.get("operation")
            if operation == "call_tool" and isinstance(request.get("name"), str):
                tool_name = request["name"]
            request_deadline = time.monotonic() + self.server.runtime_timeout
            result = self.server.runtime.run(
                self.server.runtime.service.execute(request, deadline=request_deadline),
                timeout=self.server.runtime_timeout,
            )
            tool_name = result.tool_name
            status = result.log_status
            response_status = result.status_code
            self._write_payload(result.payload, response_status)
        except _HTTPFailure as exc:
            response_status = exc.status_code
            self._write_payload(_error_payload(exc.code, exc.message), response_status)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            # A cancelled/expired runtime future has an unknown outcome for a
            # tools/call.  Never turn it into a replayable success or 500.
            if request is not None and request.get("operation") == "call_tool":
                payload = _unknown_outcome_payload()
                response_status = HTTPStatus.BAD_GATEWAY
                status = "unknown_outcome"
            else:
                payload = _error_payload("timeout", "bridge operation timed out")
                response_status = HTTPStatus.GATEWAY_TIMEOUT
            self._write_payload(payload, response_status)
        except (BrokenPipeError, ConnectionResetError):
            status = "client_disconnected"
        except Exception:
            # Never write exception text: it may contain request data, result
            # data, host details, or credentials from a lower layer.  A
            # call_tool runtime failure is conservatively unknown because the
            # request may already have been dispatched.
            if request is not None and request.get("operation") == "call_tool":
                response_status = HTTPStatus.BAD_GATEWAY
                status = "unknown_outcome"
                self._write_payload(_unknown_outcome_payload(), response_status)
            else:
                response_status = HTTPStatus.INTERNAL_SERVER_ERROR
                self._write_payload(_error_payload("internal_error", "bridge request failed"), response_status)
        finally:
            self._log_result(tool_name, status, started)
            self.close_connection = True

    def do_POST(self) -> None:
        self._handle(None)

    def do_GET(self) -> None:
        # A GET is intentionally limited to the side-effect-free health status.
        self._handle({"operation": "health"})

    def do_PUT(self) -> None:
        self._write_payload(_error_payload("method_not_allowed", "method not allowed"), HTTPStatus.METHOD_NOT_ALLOWED)

    do_DELETE = do_PUT
    do_PATCH = do_PUT


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True, help="trusted bearer-token file")
    parser.add_argument("--bind", default=DEFAULT_BIND, help="HTTP bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port")
    parser.add_argument("--path", default=DEFAULT_PATH, help="HTTP bridge path")
    parser.add_argument(
        "--allowlist-file",
        "--allowlist",
        dest="allowlist_file",
        type=Path,
        help="trusted JSON tool allowlist",
    )
    parser.add_argument(
        "--allow-tool",
        action="append",
        default=None,
        help="allow one tool name (repeat; overrides --allowlist-file)",
    )
    parser.add_argument(
        "--call-timeout",
        "--timeout",
        dest="call_timeout",
        type=float,
        default=DEFAULT_CALL_TIMEOUT,
        help="per-operation MCP timeout in seconds",
    )
    return parser.parse_args(argv)


def _validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise BridgeConfigurationError("port must be an integer between 0 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # CLI startup owns logging configuration; importing the bridge remains
    # silent and embedding callers can configure their own handlers.
    _configure_logging()
    try:
        token = load_token(args.token_file)
        _validate_port(args.port)
        bridge_path = _normalize_path(args.path)
        allowlist = frozenset(args.allow_tool) if args.allow_tool is not None else load_allowlist(args.allowlist_file)
        service = BridgeService(
            allowlist=allowlist,
            call_timeout=args.call_timeout,
        )
        runtime = AsyncBridgeRuntime(service)
        runtime.start()
        server = BridgeHTTPServer(
            (args.bind, args.port),
            BridgeRequestHandler,
            token=token,
            bridge_path=bridge_path,
            runtime=runtime,
        )
    except (BridgeConfigurationError, OSError) as exc:
        # Startup failures are deliberately generic and never include the
        # token contents or lower-layer exception text.
        if "runtime" in locals():
            runtime.close()
        print(f"bridge startup failed: {exc}", flush=True)
        return 1

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by deployment smoke tests
    raise SystemExit(main())
