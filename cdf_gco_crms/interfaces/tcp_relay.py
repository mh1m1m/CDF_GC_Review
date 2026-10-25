"""Ingress-only TCP relay for the remote MCP deployment (deploy/remote-mcp/compose.yaml).

Docker does not publish ports for a container that is attached only to an ``internal: true`` network, and attaching
the MCP server to a routable network would also give it outbound internet access. This relay sits on both networks:
it accepts connections on the edge network and forwards raw bytes to one fixed upstream on the isolated network.
TLS is not terminated here — the bytes are relayed unchanged, so the certificate, OAuth checks and transport security
stay in the MCP server. The relay holds no secrets, reads no data and only ever connects to its configured upstream.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal

LOG = logging.getLogger("cdf.tcp_relay")
CHUNK = 64 * 1024


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, idle: float) -> None:
    try:
        while True:
            data = await asyncio.wait_for(reader.read(CHUNK), timeout=idle)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        # closing a broken socket must not crash the relay
        with contextlib.suppress(Exception):
            writer.close()


class Relay:
    def __init__(self, upstream_host: str, upstream_port: int, *, max_connections: int = 64, idle_seconds: float = 300.0,
                 connect_timeout: float = 5.0):
        self.upstream = (upstream_host, upstream_port)
        self.slots = asyncio.Semaphore(max_connections)
        self.max_connections = max_connections
        self.idle = idle_seconds
        self.connect_timeout = connect_timeout
        self.active = 0

    async def handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        if self.slots.locked():
            client_writer.close()                     # at capacity: refuse rather than queue unbounded
            return
        async with self.slots:
            self.active += 1
            try:
                up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*self.upstream), timeout=self.connect_timeout)
            except (OSError, asyncio.TimeoutError) as exc:
                LOG.warning("upstream unavailable: %s", type(exc).__name__)
                client_writer.close()
                self.active -= 1
                return
            await asyncio.gather(_pipe(client_reader, up_writer, self.idle), _pipe(up_reader, client_writer, self.idle))
            self.active -= 1


async def serve(listen_host: str, listen_port: int, relay: Relay) -> None:
    server = await asyncio.start_server(relay.handle, listen_host, listen_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:   # pragma: no cover - non-POSIX
            pass
    LOG.info("relaying %s:%s -> %s:%s", listen_host, listen_port, *relay.upstream)
    async with server:
        await stop.wait()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--listen-host", default="0.0.0.0")       # nosec B104 - the container port is published to one approved bind IP
    p.add_argument("--listen-port", type=int, default=8443)
    p.add_argument("--upstream-host", required=True)
    p.add_argument("--upstream-port", type=int, default=8443)
    p.add_argument("--max-connections", type=int, default=64)
    p.add_argument("--idle-seconds", type=float, default=300.0)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(serve(a.listen_host, a.listen_port, Relay(a.upstream_host, a.upstream_port,
                                                          max_connections=a.max_connections, idle_seconds=a.idle_seconds)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
