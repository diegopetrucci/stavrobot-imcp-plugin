from __future__ import annotations

import asyncio
import json
import types as stdlib_types
import unittest
from unittest.mock import patch

import anyio
from mcp.shared.message import SessionMessage
from mcp import types as mcp_types

from stavrobot_imcp import transport


class _FakeReader(asyncio.StreamReader):
    pass


class _FakeWriter:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []
        self.closed = False
        self.wait_closed_called = False

    def is_closing(self) -> bool:
        return self.closed

    def write(self, payload: bytes) -> None:
        self.payloads.append(payload)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_called = True


class _FakeBonjour:
    def __init__(self, infos: dict[str, object | None]) -> None:
        self.zeroconf = object()
        self.infos = infos
        self.requested: list[tuple[str, str, int]] = []
        self.closed = False

    async def async_get_service_info(self, service_type: str, name: str, *, timeout: int) -> object | None:
        self.requested.append((service_type, name, timeout))
        return self.infos.get(name)

    async def async_close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(
        self,
        _zeroconf: object,
        service_type: str,
        *,
        listener: object,
        names: tuple[str, ...] = ("iMCP._mcp._tcp.local.",),
    ) -> None:
        self.cancelled = False
        for name in names:
            listener.add_service(object(), service_type, name)

    async def async_cancel(self) -> None:
        self.cancelled = True


class _ResetReader:
    async def readline(self) -> bytes:
        raise ConnectionResetError("peer reset")


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def test_selects_local_service_port_without_using_advertised_addresses(self) -> None:
        infos = [
            stdlib_types.SimpleNamespace(
                name="remote._mcp._tcp.local.",
                server="another-host.local.",
                port=4321,
                addresses=[b"192.0.2.10"],
            ),
            stdlib_types.SimpleNamespace(
                name="iMCP._mcp._tcp.local.",
                server="My-Mac.local.",
                port=54321,
                addresses=[b"192.0.2.20", b"10.0.0.20"],
            ),
        ]

        port = transport.select_local_service_port(infos, local_hostnames={"my-mac.local"})

        self.assertEqual(port, 54321)

    def test_absent_local_service_fails_closed(self) -> None:
        with self.assertRaises(transport.NoLocalServiceError):
            transport.select_local_service_port(
                [
                    stdlib_types.SimpleNamespace(
                        name="remote._mcp._tcp.local.",
                        server="other.local.",
                        port=1234,
                    )
                ],
                local_hostnames={"this-host.local"},
            )

    def test_ambiguous_local_services_fail_closed(self) -> None:
        infos = [
            {"name": "first._mcp._tcp.local.", "server": "this-host.local.", "port": 1111},
            {"name": "second._mcp._tcp.local.", "server": "this-host.local.", "port": 2222},
        ]

        with self.assertRaises(transport.AmbiguousLocalServiceError):
            transport.select_local_service_port(infos, local_hostnames={"this-host.local"})

    def test_invalid_local_service_port_fails_closed(self) -> None:
        for port in (0, -1, 65536, True):
            with self.subTest(port=port):
                with self.assertRaises(transport.InvalidLocalServiceError):
                    transport.select_local_service_port(
                        [
                            {
                                "name": "iMCP._mcp._tcp.local.",
                                "server": "this-host.local.",
                                "port": port,
                            }
                        ],
                        local_hostnames={"this-host.local"},
                    )

    def test_default_host_aliases_do_not_use_reverse_dns(self) -> None:
        with patch.object(transport.socket, "gethostname", return_value="this-host"):
            with patch.object(transport.socket, "getfqdn", side_effect=AssertionError("reverse DNS used")):
                names = transport._default_local_hostnames()

        self.assertIn("this-host", names)
        self.assertIn("this-host.local", names)

    async def test_zeroconf_discovery_uses_service_type_and_dynamic_port(self) -> None:
        info = stdlib_types.SimpleNamespace(
            name="iMCP._mcp._tcp.local.",
            server="this-host.local.",
            port=61234,
            addresses=[b"198.51.100.7"],
        )
        fake_zeroconf = _FakeBonjour({"iMCP._mcp._tcp.local.": info})
        browser_instances: list[_FakeBrowser] = []

        def browser_factory(
            zeroconf: object,
            service_type: str,
            *,
            listener: object,
        ) -> _FakeBrowser:
            browser = _FakeBrowser(zeroconf, service_type, listener=listener)
            browser_instances.append(browser)
            return browser

        port = await transport.discover_local_service_port(
            timeout=0.01,
            close_timeout=0.2,
            local_hostnames={"this-host.local"},
            zeroconf_factory=lambda: fake_zeroconf,
            browser_factory=browser_factory,
        )

        self.assertEqual(port, 61234)
        self.assertEqual(
            fake_zeroconf.requested[0][0],
            transport.SERVICE_TYPE,
        )
        self.assertTrue(fake_zeroconf.closed)
        self.assertTrue(browser_instances[0].cancelled)

    async def test_discovery_with_no_observed_services_fails_and_cleans_up(self) -> None:
        fake_zeroconf = _FakeBonjour({})
        browser_instances: list[_FakeBrowser] = []

        def browser_factory(
            zeroconf: object,
            service_type: str,
            *,
            listener: object,
        ) -> _FakeBrowser:
            browser = _FakeBrowser(zeroconf, service_type, listener=listener, names=())
            browser_instances.append(browser)
            return browser

        with self.assertRaises(transport.NoLocalServiceError):
            await transport.discover_local_service_port(
                timeout=0.01,
                close_timeout=0.2,
                local_hostnames={"this-host.local"},
                zeroconf_factory=lambda: fake_zeroconf,
                browser_factory=browser_factory,
            )

        self.assertTrue(fake_zeroconf.closed)
        self.assertTrue(browser_instances[0].cancelled)

    async def test_discovery_with_ambiguous_local_services_fails_and_cleans_up(self) -> None:
        names = ("first._mcp._tcp.local.", "second._mcp._tcp.local.")
        fake_zeroconf = _FakeBonjour(
            {
                names[0]: stdlib_types.SimpleNamespace(
                    name=names[0], server="this-host.local.", port=1111
                ),
                names[1]: stdlib_types.SimpleNamespace(
                    name=names[1], server="this-host.local.", port=2222
                ),
            }
        )
        browser_instances: list[_FakeBrowser] = []

        def browser_factory(
            zeroconf: object,
            service_type: str,
            *,
            listener: object,
        ) -> _FakeBrowser:
            browser = _FakeBrowser(zeroconf, service_type, listener=listener, names=names)
            browser_instances.append(browser)
            return browser

        with self.assertRaises(transport.AmbiguousLocalServiceError):
            await transport.discover_local_service_port(
                timeout=0.01,
                close_timeout=0.2,
                local_hostnames={"this-host.local"},
                zeroconf_factory=lambda: fake_zeroconf,
                browser_factory=browser_factory,
            )

        self.assertTrue(fake_zeroconf.closed)
        self.assertTrue(browser_instances[0].cancelled)

    async def test_discovery_with_unresolved_service_fails_and_cleans_up(self) -> None:
        name = "iMCP._mcp._tcp.local."
        fake_zeroconf = _FakeBonjour({name: None})
        browser_instances: list[_FakeBrowser] = []

        def browser_factory(
            zeroconf: object,
            service_type: str,
            *,
            listener: object,
        ) -> _FakeBrowser:
            browser = _FakeBrowser(zeroconf, service_type, listener=listener, names=(name,))
            browser_instances.append(browser)
            return browser

        with self.assertRaises(transport.DiscoveryError):
            await transport.discover_local_service_port(
                timeout=0.01,
                close_timeout=0.2,
                local_hostnames={"this-host.local"},
                zeroconf_factory=lambda: fake_zeroconf,
                browser_factory=browser_factory,
            )

        self.assertTrue(fake_zeroconf.closed)
        self.assertTrue(browser_instances[0].cancelled)

    async def test_discovery_resolution_deadline_fails_and_cleans_up(self) -> None:
        name = "iMCP._mcp._tcp.local."

        class _SlowBonjour(_FakeBonjour):
            async def async_get_service_info(
                self,
                service_type: str,
                service_name: str,
                *,
                timeout: int,
            ) -> object | None:
                await asyncio.sleep(0.2)
                return await super().async_get_service_info(
                    service_type,
                    service_name,
                    timeout=timeout,
                )

        fake_zeroconf = _SlowBonjour(
            {
                name: stdlib_types.SimpleNamespace(
                    name=name,
                    server="this-host.local.",
                    port=61234,
                )
            }
        )
        browser_instances: list[_FakeBrowser] = []

        def browser_factory(
            zeroconf: object,
            service_type: str,
            *,
            listener: object,
        ) -> _FakeBrowser:
            browser = _FakeBrowser(zeroconf, service_type, listener=listener, names=(name,))
            browser_instances.append(browser)
            return browser

        with self.assertRaises(transport.DiscoveryError):
            await transport.discover_local_service_port(
                timeout=0.01,
                close_timeout=0.2,
                local_hostnames={"this-host.local"},
                zeroconf_factory=lambda: fake_zeroconf,
                browser_factory=browser_factory,
            )

        self.assertTrue(fake_zeroconf.closed)
        self.assertTrue(browser_instances[0].cancelled)

    async def test_connection_forces_loopback_and_keeps_dynamic_port(self) -> None:
        reader = _FakeReader()
        writer = _FakeWriter()
        observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def fake_open_connection(
            *args: object,
            **kwargs: object,
        ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            observed.append((args, kwargs))
            return reader, writer  # type: ignore[return-value]

        with patch.object(transport.asyncio, "open_connection", fake_open_connection):
            result = await transport.open_loopback_connection(61234, timeout=0.2)

        self.assertIs(result[0], reader)
        self.assertIs(result[1], writer)
        self.assertEqual(
            observed,
            [(("127.0.0.1", 61234), {"limit": transport.MAX_MESSAGE_BYTES})],
        )

    async def test_large_jsonrpc_frame_over_64k_is_preserved(self) -> None:
        reader = asyncio.StreamReader(limit=transport.MAX_MESSAGE_BYTES)
        payload = {"jsonrpc": "2.0", "id": 8, "result": {"text": "x" * 70_000}}
        reader.feed_data((json.dumps(payload) + "\n").encode("utf-8"))

        incoming = await transport._TCPReadStream(reader).receive()

        self.assertIsInstance(incoming, SessionMessage)
        assert isinstance(incoming, SessionMessage)
        self.assertEqual(len(incoming.message.result["text"]), 70_000)  # type: ignore[attr-defined]

    async def test_over_limit_jsonrpc_frame_is_a_closed_broken_transport(self) -> None:
        reader = asyncio.StreamReader(limit=transport.MAX_MESSAGE_BYTES)
        reader.feed_data(
            b'{"jsonrpc":"2.0","id":9,"result":{"text":"'
            + (b"x" * transport.MAX_MESSAGE_BYTES)
            + b'"}}\n'
        )
        read_stream = transport._TCPReadStream(reader)

        with self.assertRaises(transport.FrameTooLargeError) as raised:
            await read_stream.receive()

        self.assertIsInstance(raised.exception, anyio.BrokenResourceError)
        with self.assertRaises(anyio.ClosedResourceError):
            await read_stream.receive()

    async def test_reset_read_is_clean_async_stream_termination(self) -> None:
        read_stream = transport._TCPReadStream(_ResetReader())  # type: ignore[arg-type]

        self.assertEqual([item async for item in read_stream], [])
        with self.assertRaises(anyio.ClosedResourceError):
            await read_stream.receive()

    async def test_newline_jsonrpc_framing_uses_sdk_messages(self) -> None:
        reader = _FakeReader()
        writer = _FakeWriter()
        reader.feed_data(b'{"jsonrpc":"2.0","id":7,"result":{"ok":true}}\n')

        read_stream = transport._TCPReadStream(reader)
        write_stream = transport._TCPWriteStream(writer)
        incoming = await read_stream.receive()
        await write_stream.send(
            SessionMessage(
                mcp_types.JSONRPCNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                )
            )
        )

        self.assertIsInstance(incoming, SessionMessage)
        assert isinstance(incoming, SessionMessage)
        self.assertEqual(incoming.message.id, 7)  # type: ignore[attr-defined]
        self.assertEqual(
            json.loads(writer.payloads[0]),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

    async def test_bounded_await_cancellation_does_not_hang(self) -> None:
        release = asyncio.Event()

        async def stubborn_cleanup() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

        cleanup = asyncio.create_task(transport._bounded_await(stubborn_cleanup(), 0.03))
        await asyncio.sleep(0.005)
        started = asyncio.get_running_loop().time()
        cleanup.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(cleanup, 0.2)
        elapsed = asyncio.get_running_loop().time() - started
        self.assertLess(elapsed, 0.2)
        release.set()
        await asyncio.sleep(0)

    async def test_transport_shutdown_closes_tcp_writer_and_streams(self) -> None:
        reader = _FakeReader()
        writer = _FakeWriter()

        async def fake_open_connection(
            *_args: object,
            **_kwargs: object,
        ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            return reader, writer  # type: ignore[return-value]

        async def fake_discovery() -> int:
            return 61235

        with patch.object(transport.asyncio, "open_connection", fake_open_connection):
            async with transport.loopback_transport(
                discovery=fake_discovery,
                close_timeout=0.2,
            ) as (_read_stream, write_stream):
                await write_stream.send(
                    SessionMessage(
                        mcp_types.JSONRPCNotification(
                            jsonrpc="2.0",
                            method="notifications/initialized",
                        )
                    )
                )

        self.assertTrue(writer.closed)
        self.assertTrue(writer.wait_closed_called)
        with self.assertRaises(anyio.ClosedResourceError):
            await write_stream.send(
                SessionMessage(
                    mcp_types.JSONRPCNotification(
                        jsonrpc="2.0",
                        method="notifications/initialized",
                    )
                )
            )

    async def test_official_client_session_uses_adapted_streams(self) -> None:
        async def fake_mcp_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request = json.loads(await reader.readline())
                response = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "fake", "version": "1"},
                    },
                }
                writer.write((json.dumps(response) + "\n").encode("utf-8"))
                await writer.drain()
                await reader.readline()  # notifications/initialized
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(fake_mcp_server, "127.0.0.1", 0)
        assert server.sockets
        port = server.sockets[0].getsockname()[1]

        async def fake_discovery() -> int:
            return port

        try:
            async with transport.open_imcp_session(
                discovery=fake_discovery,
                connect_timeout=0.2,
                close_timeout=0.2,
            ) as session:
                result = await session.initialize()
                self.assertEqual(result.server_info.name, "fake")
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
