"""Official MCP stdio transport for the bundled iMCP server.

The iMCP application ships ``imcp-server`` as the supported MCP entrypoint.
This module deliberately delegates process management and JSON-RPC framing to
the official MCP Python SDK instead of depending on iMCP's private network
implementation.
"""

from __future__ import annotations

import asyncio
import math
import os
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeAlias

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

DEFAULT_SERVER_PATH = Path("/Applications/iMCP.app/Contents/MacOS/imcp-server")
DEFAULT_STARTUP_TIMEOUT = 5.0
# For the pinned mcp==2.1.1 SDK, stdio shutdown can spend 0.5s flushing,
# 2s waiting for a graceful exit, 2s escalating SIGTERM to SIGKILL, and 2s
# observing the killed process.
# This parameter is a safety floor for callers; the SDK owns the actual
# escalation deadline and the wrapper never cancels its __aexit__.
SDK_SHUTDOWN_BUDGET = 6.5
MIN_SHUTDOWN_TIMEOUT = SDK_SHUTDOWN_BUDGET + 0.5
DEFAULT_SHUTDOWN_TIMEOUT = MIN_SHUTDOWN_TIMEOUT

ServerPath: TypeAlias = str | os.PathLike[str]


class TransportConfigurationError(ValueError):
    """Raised when trusted stdio transport configuration is invalid."""


def _validate_timeout(value: float, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransportConfigurationError(f"{label} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise TransportConfigurationError(f"{label} must be a finite positive number")
    return result


def _validate_shutdown_timeout(value: float) -> float:
    result = _validate_timeout(value, label="shutdown timeout")
    if result < MIN_SHUTDOWN_TIMEOUT:
        raise TransportConfigurationError(
            f"shutdown timeout must be at least {MIN_SHUTDOWN_TIMEOUT:g} seconds"
        )
    return result


def _validate_server_path(value: ServerPath) -> Path:
    """Validate the executable before handing it to the SDK process launcher."""

    try:
        path = Path(value)
    except (TypeError, ValueError) as exc:
        raise TransportConfigurationError("iMCP server path is invalid") from exc

    if not path.is_absolute():
        raise TransportConfigurationError("iMCP server path must be absolute")
    try:
        path_stat = path.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"iMCP server executable not found: {path}") from exc
    except OSError as exc:
        raise TransportConfigurationError("iMCP server path could not be inspected") from exc
    except ValueError as exc:
        raise TransportConfigurationError("iMCP server path is invalid") from exc

    if not stat.S_ISREG(path_stat.st_mode):
        raise TransportConfigurationError("iMCP server path must be a regular file")
    if not os.access(path, os.X_OK):
        raise PermissionError(f"iMCP server executable is not executable: {path}")
    return path


CLIENT_CREDENTIAL_ENV = "IMCP_CLIENT_CREDENTIAL"


def load_client_credential(path: ServerPath) -> str:
    """Read an iMCP 1.8.2+ client credential from a private owned file.

    Errors are deliberately generic and never include the file contents.
    """

    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            file_stat = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_uid != os.getuid()
                or stat.S_IMODE(file_stat.st_mode) not in (0o400, 0o600)
            ):
                raise TransportConfigurationError(
                    "client credential file must be an owned regular file with mode 0400 or 0600"
                )
            credential = handle.read().decode("utf-8").strip()
    except TransportConfigurationError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError):
        raise TransportConfigurationError("client credential file could not be read") from None
    if not credential or any(character.isspace() for character in credential):
        raise TransportConfigurationError("client credential file is empty or contains whitespace")
    return credential


def _server_parameters(
    server_path: ServerPath,
    client_credential: str | None = None,
) -> StdioServerParameters:
    """Build SDK launch parameters without invoking a shell."""

    path = _validate_server_path(server_path)
    env = None
    if client_credential is not None:
        # An explicit env replaces the SDK's safe default, so start from it.
        env = {**get_default_environment(), CLIENT_CREDENTIAL_ENV: client_credential}
    return StdioServerParameters(command=os.fspath(path), args=[], env=env)


@asynccontextmanager
async def _stdio_transport(parameters: StdioServerParameters) -> AsyncIterator[Any]:
    """Run the SDK stdio client with child stderr isolated from bridge logs."""

    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(parameters, errlog=errlog) as streams:
            yield streams


async def _enter_context_bounded(context: Any, timeout: float, *, operation: str) -> Any:
    """Enter an SDK context in its owning task with a startup bound."""

    enter_method = getattr(context, "__aenter__", None)
    if not callable(enter_method):
        raise TypeError("stdio transport context is not an async context manager")
    try:
        # AnyIO cancel scopes and task groups must be entered and exited in the
        # same task.  ``asyncio.timeout`` cancels this task instead of moving
        # context entry to a helper task as ``wait_for`` would.
        async with asyncio.timeout(timeout):
            return await enter_method()
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{operation} timed out") from exc


async def _close_context(
    context: Any,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: Any,
) -> None:
    """Run SDK context teardown in the task that entered it.

    The official SDK's ``stdio_client`` exit path already closes stdin, waits
    for graceful exit, escalates to SIGKILL, and reaps the process with bounded
    internal waits.  Do not put an asyncio timeout or cancellation around it:
    AnyIO cancel scopes and task groups must exit in their owning task.
    """

    exit_method = getattr(context, "__aexit__", None)
    if callable(exit_method):
        await exit_method(exc_type, exc_value, traceback)


@asynccontextmanager
async def open_imcp_session(
    *,
    server_path: ServerPath = DEFAULT_SERVER_PATH,
    client_info: types.Implementation | None = None,
    read_timeout_seconds: float | None = None,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
    shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    client_credential: str | None = None,
) -> AsyncIterator[ClientSession]:
    """Yield an official SDK ``ClientSession`` connected to bundled iMCP.

    ``server_path`` is injectable for deterministic tests, but production
    callers use the fixed executable bundled in ``/Applications/iMCP.app``.
    ``shutdown_timeout`` is a floor-only compatibility setting: values below
    the pinned SDK escalation budget plus margin are rejected, but this wrapper
    never imposes its own cancellation deadline. The official SDK owns stdio
    teardown and its bounded escalation. The caller owns the normal MCP
    lifecycle and must call ``await session.initialize()`` before listing or
    calling tools.
    """

    startup_bound = _validate_timeout(startup_timeout, label="startup timeout")
    _validate_shutdown_timeout(shutdown_timeout)
    if read_timeout_seconds is not None:
        read_timeout_seconds = _validate_timeout(read_timeout_seconds, label="read timeout")

    parameters = _server_parameters(server_path, client_credential)
    transport_context = _stdio_transport(parameters)
    transport_entered = False
    session_context: ClientSession | None = None
    session_entered = False
    body_exc_type: type[BaseException] | None = None
    body_exc_value: BaseException | None = None
    body_traceback: Any = None
    startup_deadline = asyncio.get_running_loop().time() + startup_bound

    try:
        streams = await _enter_context_bounded(
            transport_context,
            startup_bound,
            operation="iMCP stdio startup",
        )
        transport_entered = True
        read_stream, write_stream = streams
        session_context = ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=read_timeout_seconds,
            client_info=client_info,
        )
        remaining_startup = startup_deadline - asyncio.get_running_loop().time()
        if remaining_startup <= 0:
            raise TimeoutError("MCP client startup timed out")
        await _enter_context_bounded(
            session_context,
            remaining_startup,
            operation="MCP client startup",
        )
        session_entered = True
        try:
            yield session_context
        except BaseException:
            body_exc_type, body_exc_value, body_traceback = sys.exc_info()
            raise
    finally:
        cleanup_error: BaseException | None = None
        if session_entered and session_context is not None:
            try:
                # ClientSession and stdio transport each receive their own full
                # cleanup budget; the latter must not inherit a spent deadline.
                await _close_context(
                    session_context,
                    body_exc_type,
                    body_exc_value,
                    body_traceback,
                )
            except BaseException as exc:
                cleanup_error = exc
        if transport_entered:
            try:
                await _close_context(
                    transport_context,
                    body_exc_type,
                    body_exc_value,
                    body_traceback,
                )
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None and body_exc_value is None:
            raise cleanup_error


__all__ = [
    "DEFAULT_SERVER_PATH",
    "DEFAULT_SHUTDOWN_TIMEOUT",
    "DEFAULT_STARTUP_TIMEOUT",
    "MIN_SHUTDOWN_TIMEOUT",
    "TransportConfigurationError",
    "open_imcp_session",
]
