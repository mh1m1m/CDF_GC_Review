"""Ingress relay for the remote MCP deployment: bytes pass unchanged, capacity is bounded, upstream failure is clean."""
from __future__ import annotations

import asyncio

from cdf_gco_crms.interfaces.tcp_relay import Relay


async def _echo_server():
    async def echo(r, w):
        while data := await r.read(65536):
            w.write(data[::-1])            # reversed, so a pass-through is distinguishable from a loop-back
            await w.drain()
        w.close()
    return await asyncio.start_server(echo, "127.0.0.1", 0)


def test_relay_forwards_bytes_unchanged_and_refuses_beyond_capacity():
    async def run():
        upstream = await _echo_server()
        up_port = upstream.sockets[0].getsockname()[1]
        relay = Relay("127.0.0.1", up_port, max_connections=1, idle_seconds=5)
        front = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
        port = front.sockets[0].getsockname()[1]
        r1, w1 = await asyncio.open_connection("127.0.0.1", port)
        payload = bytes(range(256)) * 400              # binary, larger than one chunk: TLS records are opaque bytes
        w1.write(payload); await w1.drain()
        got = await asyncio.wait_for(r1.readexactly(len(payload)), 5)
        assert got == payload[::-1]
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)     # second client while the only slot is taken
        assert await asyncio.wait_for(r2.read(1), 5) == b""
        w1.close(); w2.close()
        front.close(); upstream.close()
    asyncio.run(run())


def test_relay_closes_the_client_when_the_upstream_is_down():
    async def run():
        relay = Relay("127.0.0.1", 9, idle_seconds=1, connect_timeout=1)   # discard port: nothing listens
        front = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
        r, w = await asyncio.open_connection("127.0.0.1", front.sockets[0].getsockname()[1])
        assert await asyncio.wait_for(r.read(1), 5) == b""
        assert relay.active == 0
        w.close(); front.close()
    asyncio.run(run())
