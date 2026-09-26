"""Loopback transport for iMCP's Bonjour-advertised MCP endpoint.

The iMCP application advertises a local-only TCP listener with a dynamic port.
Its Bonjour record can contain interface addresses that are not valid from every
client context, so this module uses Bonjour only to discover the port.  The TCP
connection is always made to the IPv4 loopback address.

The transport exposes the stream pair expected by the official MCP Python SDK.
Callers normally use :func:`open_imcp_session` and then use the SDK's
``ClientSession`` methods as usual; this module does not invoke an MCP tool on
behalf of its callers.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeAlias

import anyio
from mcp import ClientSession, types
from mcp.shared.message import SessionMessage
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

SERVICE_TYPE = "_mcp._tcp.local."
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DISCOVERY_TIMEOUT = 3.0
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_CLOSE_TIMEOUT = 2.0
# Match the bundled iMCP proxy's 10 MiB newline-delimited message buffer.
MAX_MESSAGE_BYTES = 10 * 1024 * 1024


class DiscoveryError(RuntimeError):
    """Base error for an unusable Bonjour discovery result."""


class NoLocalServiceError(DiscoveryError):
    """Raised when Bonjour has no resolvable service for the local host."""


class AmbiguousLocalServiceError(DiscoveryError):
    """Raised when more than one local service could be the iMCP endpoint."""


class InvalidLocalServiceError(DiscoveryError):
    """Raised when the selected local service has an invalid TCP port."""


class LoopbackConnectionError(ConnectionError):
    """Raised when the discovered loopback endpoint cannot be opened."""


class FrameTooLargeError(anyio.BrokenResourceError):
    """Raised when a newline-delimited JSON-RPC frame exceeds the bound."""


@dataclass(frozen=True, slots=True)
class BonjourService:
    """The Bonjour fields needed for safe endpoint selection.

    Deliberately does not retain ``addresses`` from ``zeroconf.ServiceInfo``.
    Those addresses are discovery metadata only and are never connection
    targets.
    """

    name: str
    server: str
    port: int


ServiceInfoLike: TypeAlias = BonjourService | object
DiscoveryFactory: TypeAlias = Callable[[], Awaitable[int]]


def _normalize_hostname(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip(".").casefold()


def _hostname_aliases(value: object) -> set[str]:
    normalized = _normalize_hostname(value)
    if not normalized:
        return set()

    aliases = {normalized}
    if normalized.endswith(".local"):
        aliases.add(normalized.removesuffix(".local"))
    else:
        aliases.add(f"{normalized}.local")
    return aliases


def _default_local_hostnames() -> frozenset[str]:
    """Return names that can identify this host in a Bonjour SRV record."""

    names: set[str] = {"localhost", "localhost.local"}
    names.update(_hostname_aliases(socket.gethostname()))
    return frozenset(names)


def _service_fields(info: ServiceInfoLike) -> tuple[str, str, object] | None:
    """Read only name/server/port from a zeroconf result.

    ``ServiceInfo`` is intentionally treated structurally so selection tests do
    not need to construct a live zeroconf object.  In particular, this function
    never reads its advertised address fields.
    """

    if isinstance(info, Mapping):
        name = info.get("name")
        server = info.get("server")
        port = info.get("port")
    else:
        name = getattr(info, "name", None)
        server = getattr(info, "server", None)
        port = getattr(info, "port", None)

    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(server, str) or not server.strip():
        return None
    return name, server, port


def _service_record(info: ServiceInfoLike, local_names: Collection[str]) -> BonjourService | None:
    fields = _service_fields(info)
    if fields is None:
        return None

    name, server, port = fields
    if _normalize_hostname(server) not in local_names:
        return None
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise InvalidLocalServiceError("local Bonjour service has an invalid TCP port")
    return BonjourService(name=name, server=server, port=port)


def select_local_service(
    service_infos: Iterable[ServiceInfoLike],
    *,
    local_hostnames: Collection[str] | None = None,
) -> BonjourService:
    """Select exactly one local Bonjour service without using its addresses.

    ``service_infos`` may contain remote services or incomplete records; those
    are ignored.  A local service is identified by its SRV ``server`` hostname,
    matched against this host's hostname aliases.  Duplicate callbacks for the
    same service name are accepted only when they agree on the port.  Since the
    iMCP record has no reliable instance marker, any distinct local service or
    conflicting update fails closed.
    """

    if local_hostnames is None:
        names = _default_local_hostnames()
    else:
        normalized_names: set[str] = set()
        for value in local_hostnames:
            normalized_names.update(_hostname_aliases(value))
        names = frozenset(normalized_names)

    local_services: dict[str, BonjourService] = {}
    for info in service_infos:
        record = _service_record(info, names)
        if record is None:
            continue

        key = _normalize_hostname(record.name) or record.name
        previous = local_services.get(key)
        if previous is not None and previous.port != record.port:
            raise AmbiguousLocalServiceError("local Bonjour service changed ports during discovery")
        local_services[key] = record

    if not local_services:
        raise NoLocalServiceError("Bonjour discovery found no local iMCP service")
    if len(local_services) != 1:
        raise AmbiguousLocalServiceError("Bonjour discovery found multiple local iMCP services")
    return next(iter(local_services.values()))


def select_local_service_port(
    service_infos: Iterable[ServiceInfoLike],
    *,
    local_hostnames: Collection[str] | None = None,
) -> int:
    """Return the dynamic port from the one selected local service."""

    return select_local_service(service_infos, local_hostnames=local_hostnames).port


class _ServiceNameListener:
    """Collect service names while zeroconf resolves their details later."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def add_service(self, _zeroconf: object, _service_type: str, name: str) -> None:
        self.names.add(name)

    def update_service(self, _zeroconf: object, _service_type: str, name: str) -> None:
        self.names.add(name)

    def remove_service(self, _zeroconf: object, _service_type: str, name: str) -> None:
        self.names.discard(name)


def _validate_timeout(value: float, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return result


def _consume_task_result(task: asyncio.Future[Any]) -> None:
    """Consume an abandoned cleanup task's eventual result or exception."""

    if not task.cancelled():
        with contextlib.suppress(BaseException):
            task.exception()


async def _cancel_task_bounded(task: asyncio.Future[Any], timeout: float) -> None:
    """Cancel a cleanup task without waiting beyond the remaining bound."""

    task.cancel()
    if task.done():
        _consume_task_result(task)
        return
    if timeout <= 0:
        task.add_done_callback(_consume_task_result)
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
        # A cancellation handler is allowed to take time or ignore the
        # cancellation.  Detach it after the bound rather than hanging the
        # transport teardown on it.
        if not task.done():
            task.cancel()
            task.add_done_callback(_consume_task_result)
        else:
            _consume_task_result(task)


async def _bounded_await(awaitable: Awaitable[Any], timeout: float) -> None:
    """Await cleanup while preserving a caller cancellation and its bound."""

    task = asyncio.ensure_future(awaitable)
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError:
        await _cancel_task_bounded(task, 0)
    except asyncio.CancelledError:
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        await _cancel_task_bounded(task, remaining)
        raise


async def _close_bonjour(
    browser: Any | None,
    zeroconf: Any | None,
    *,
    timeout: float,
) -> None:
    cancelled = False
    for resource, method_name in ((browser, "async_cancel"), (zeroconf, "async_close")):
        if resource is None:
            continue
        method = getattr(resource, method_name, None)
        if not callable(method):
            continue
        try:
            await _bounded_await(method(), timeout)
        except asyncio.CancelledError:
            # Finish attempting every close operation before propagating the
            # caller's cancellation.  Each attempt remains bounded.
            cancelled = True
        except Exception:
            # Discovery already has a useful result or error; teardown errors
            # must not replace it.  The close operation was still bounded.
            pass
    if cancelled:
        raise asyncio.CancelledError


async def discover_local_service_port(
    *,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    local_hostnames: Collection[str] | None = None,
    zeroconf_factory: Callable[[], Any] | None = None,
    browser_factory: Callable[..., Any] | None = None,
) -> int:
    """Discover the one local iMCP service and return only its dynamic port.

    Service observation and detail resolution each have a bounded ``timeout``
    window.  Bonjour's advertised interface addresses are never inspected or
    returned.  Factories are injectable for deterministic unit tests;
    production callers should use the defaults.
    """

    discovery_timeout = _validate_timeout(timeout, label="discovery timeout")
    cleanup_timeout = _validate_timeout(close_timeout, label="close timeout")
    make_zeroconf = zeroconf_factory or AsyncZeroconf
    make_browser = browser_factory or AsyncServiceBrowser

    aiozc: Any | None = None
    browser: Any | None = None
    listener = _ServiceNameListener()
    try:
        aiozc = make_zeroconf()
        browser = make_browser(aiozc.zeroconf, SERVICE_TYPE, listener=listener)

        # Give the browser one bounded window to collect all service names so
        # that a second local service cannot be silently ignored.  Resolving
        # the collected SRV records gets its own bounded window; zeroconf
        # usually answers from its cache at this point.
        await asyncio.sleep(discovery_timeout)
        resolution_deadline = asyncio.get_running_loop().time() + discovery_timeout

        infos: list[ServiceInfoLike] = []
        for name in tuple(listener.names):
            remaining = resolution_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise DiscoveryError("Bonjour service detail resolution timed out")
            get_info = getattr(aiozc, "async_get_service_info", None)
            if not callable(get_info):
                raise DiscoveryError("Bonjour service details could not be resolved")
            try:
                info = await asyncio.wait_for(
                    get_info(
                        SERVICE_TYPE,
                        name,
                        timeout=max(1, int(remaining * 1000)),
                    ),
                    remaining,
                )
            except asyncio.TimeoutError as exc:
                raise DiscoveryError("Bonjour service detail resolution timed out") from exc
            except (ConnectionError, OSError) as exc:
                raise DiscoveryError("Bonjour service details could not be resolved") from exc
            except Exception as exc:
                raise DiscoveryError("Bonjour service details could not be resolved") from exc
            if info is None:
                raise DiscoveryError("Bonjour service details could not be resolved")
            infos.append(info)

        return select_local_service_port(infos, local_hostnames=local_hostnames)
    finally:
        await _close_bonjour(browser, aiozc, timeout=cleanup_timeout)


def _validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    return port


async def open_loopback_connection(
    port: int,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a bounded TCP connection to loopback and nowhere else."""

    target_port = _validate_port(port)
    connect_timeout = _validate_timeout(timeout, label="connect timeout")
    try:
        return await asyncio.wait_for(
            asyncio.open_connection(LOOPBACK_HOST, target_port, limit=MAX_MESSAGE_BYTES),
            connect_timeout,
        )
    except asyncio.TimeoutError as exc:
        raise LoopbackConnectionError("timed out connecting to the discovered loopback port") from exc
    except OSError as exc:
        raise LoopbackConnectionError("could not connect to the discovered loopback port") from exc


def _parse_jsonrpc_line(line: bytes) -> SessionMessage | Exception:
    """Parse one newline-delimited JSON-RPC message using SDK types."""

    try:
        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
    except ValueError as exc:
        return exc
    return SessionMessage(message)


class _TCPReadStream:
    """Adapt an asyncio TCP reader to the MCP ``ReadStream`` protocol."""

    def __init__(self, reader: asyncio.StreamReader, *, read_timeout: float | None = None) -> None:
        self._reader = reader
        self._read_timeout = read_timeout
        self._closed = False

    async def receive(self) -> SessionMessage | Exception:
        if self._closed:
            raise anyio.ClosedResourceError
        try:
            read = self._reader.readline()
            line = (
                await asyncio.wait_for(read, self._read_timeout)
                if self._read_timeout is not None
                else await read
            )
        except asyncio.TimeoutError:
            self._closed = True
            raise
        except (asyncio.LimitOverrunError, ValueError) as exc:
            self._closed = True
            raise FrameTooLargeError(
                f"JSON-RPC frame exceeds the {MAX_MESSAGE_BYTES}-byte limit"
            ) from exc
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            self._closed = True
            raise anyio.EndOfStream from exc
        if not line:
            self._closed = True
            raise anyio.EndOfStream
        return _parse_jsonrpc_line(line)

    def __aiter__(self) -> _TCPReadStream:
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        try:
            return await self.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError) as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self._closed = True

    async def __aenter__(self) -> _TCPReadStream:
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        await self.aclose()


class _TCPWriteStream:
    """Adapt the MCP SDK's ``SessionMessage`` writes to newline-delimited JSON."""

    def __init__(self, writer: asyncio.StreamWriter, *, close_timeout: float = DEFAULT_CLOSE_TIMEOUT) -> None:
        self._writer = writer
        self._close_timeout = close_timeout
        self._closed = False
        self._lock = asyncio.Lock()

    async def send(self, item: SessionMessage, /) -> None:
        if self._closed or self._writer.is_closing():
            raise anyio.ClosedResourceError

        payload = (item.message.model_dump_json(by_alias=True, exclude_unset=True) + "\n").encode("utf-8")
        async with self._lock:
            if self._closed or self._writer.is_closing():
                raise anyio.ClosedResourceError
            try:
                self._writer.write(payload)
                await self._writer.drain()
            except (ConnectionError, OSError) as exc:
                self._closed = True
                raise anyio.BrokenResourceError from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        wait_closed = getattr(self._writer, "wait_closed", None)
        if callable(wait_closed):
            with contextlib.suppress(asyncio.TimeoutError, ConnectionError, OSError):
                await asyncio.wait_for(wait_closed(), self._close_timeout)

    async def __aenter__(self) -> _TCPWriteStream:
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        await self.aclose()


async def _close_tcp_streams(read_stream: _TCPReadStream, write_stream: _TCPWriteStream) -> None:
    await read_stream.aclose()
    await write_stream.aclose()


@asynccontextmanager
async def loopback_transport(
    *,
    discovery: DiscoveryFactory | None = None,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    read_timeout: float | None = None,
    local_hostnames: Collection[str] | None = None,
    zeroconf_factory: Callable[[], Any] | None = None,
    browser_factory: Callable[..., Any] | None = None,
) -> AsyncIterator[tuple[_TCPReadStream, _TCPWriteStream]]:
    """Yield MCP-compatible streams over the discovered loopback endpoint.

    ``discovery`` is an optional no-argument async factory for tests and
    callers that own discovery orchestration.  The normal path performs a new
    Bonjour discovery for each context entry, which is important after iMCP
    restarts on a different dynamic port.
    """

    if read_timeout is not None:
        read_timeout = _validate_timeout(read_timeout, label="read timeout")
    cleanup_timeout = _validate_timeout(close_timeout, label="close timeout")

    if discovery is None:
        port = await discover_local_service_port(
            timeout=discovery_timeout,
            close_timeout=cleanup_timeout,
            local_hostnames=local_hostnames,
            zeroconf_factory=zeroconf_factory,
            browser_factory=browser_factory,
        )
    else:
        port = await discovery()

    reader, writer = await open_loopback_connection(port, timeout=connect_timeout)
    read_stream = _TCPReadStream(reader, read_timeout=read_timeout)
    write_stream = _TCPWriteStream(writer, close_timeout=cleanup_timeout)
    try:
        yield read_stream, write_stream
    finally:
        await _bounded_await(_close_tcp_streams(read_stream, write_stream), cleanup_timeout)


@asynccontextmanager
async def open_imcp_session(
    *,
    client_info: types.Implementation | None = None,
    read_timeout_seconds: float | None = None,
    **transport_options: Any,
) -> AsyncIterator[ClientSession]:
    """Yield the official MCP SDK ``ClientSession`` over the loopback transport.

    Entering this context creates the transport and SDK session.  The caller
    must still call ``await session.initialize()`` before using MCP methods,
    matching the official SDK lifecycle.
    """

    async with loopback_transport(**transport_options) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=read_timeout_seconds,
            client_info=client_info,
        ) as session:
            yield session


__all__ = [
    "AmbiguousLocalServiceError",
    "BonjourService",
    "DEFAULT_CLOSE_TIMEOUT",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_DISCOVERY_TIMEOUT",
    "DiscoveryError",
    "FrameTooLargeError",
    "InvalidLocalServiceError",
    "LOOPBACK_HOST",
    "MAX_MESSAGE_BYTES",
    "LoopbackConnectionError",
    "NoLocalServiceError",
    "SERVICE_TYPE",
    "discover_local_service_port",
    "loopback_transport",
    "open_imcp_session",
    "open_loopback_connection",
    "select_local_service",
    "select_local_service_port",
]
