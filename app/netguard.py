"""Keeps the server's own web requests (feeds, saved pages) away from link-local addresses.

169.254.0.0/16 and fe80::/10 hold cloud metadata services, which hand out credentials to whatever asks from the
machine; a feed or saved link pointed there would have FeedStash fetch them and show the reply. A couple of clouds
put theirs elsewhere (Alibaba's 100.100.100.200, AWS's IPv6 fd00:ec2::254), so those are refused too. Everything
else, your LAN included, stays reachable: people follow feeds on their own network.

Two checks: each request's host before it's sent (redirects included), for a clear error early; and the address
actually connected to, resolved once and checked at that moment. Without the second, a name could resolve to an
ordinary address for the first check and to the metadata service for the connection (DNS rebinding).
"""

import asyncio
import ipaddress
import socket

import httpcore
import httpx

_ALSO_BLOCKED = {ipaddress.ip_address("100.100.100.200"), ipaddress.ip_address("fd00:ec2::254")}


class BlockedAddress(httpx.ConnectError):
    """The address is link-local (or a metadata service); shown to users as the reason a fetch failed."""


def _blocked(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_link_local or ip in _ALSO_BLOCKED


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM, flags=socket.AI_ADDRCONFIG
    )
    return list(dict.fromkeys(info[4][0] for info in infos))  # in order, without repeats


async def check_host(host: str) -> None:
    """Raises BlockedAddress if `host` is, or resolves to, a link-local address."""
    if _blocked(host):
        raise BlockedAddress(f"FeedStash doesn't fetch link-local addresses like {host}")
    try:
        addresses = await _resolve(host)
    except OSError:
        return  # unresolvable: the request itself will fail with the usual error
    if any(_blocked(address) for address in addresses):
        raise BlockedAddress(f"FeedStash doesn't fetch link-local addresses ({host} points to one)")


class _CheckedNetwork(httpcore.AsyncNetworkBackend):
    """Connects to the addresses a host name resolves to, checked just before connecting, instead of letting the
    connection resolve the name again. TLS still checks the certificate against the host name."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend):
        self._inner = inner

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if _blocked(host):
            raise BlockedAddress(f"FeedStash doesn't fetch link-local addresses like {host}")
        try:
            addresses = [str(ipaddress.ip_address(host.split("%", 1)[0]))] if _is_address(host) else await _resolve(host)
        except OSError as exc:
            raise httpcore.ConnectError(f"Couldn't find {host} ({exc.__class__.__name__})") from exc
        if any(_blocked(address) for address in addresses):
            raise BlockedAddress(f"FeedStash doesn't fetch link-local addresses ({host} points to one)")
        error: Exception | None = None
        for address in addresses:  # each in turn, as the connection would have (IPv6 and IPv4)
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error or httpcore.ConnectError(f"Couldn't connect to {host}")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("FeedStash doesn't fetch over Unix sockets")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True


class GuardedTransport(httpx.AsyncHTTPTransport):
    """An HTTP transport that checks each request's host first (redirects are separate requests, so they're checked
    too) and connects only to addresses checked at connection time."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # httpx has no public way to give its connection pool a network backend; the pool keeps it here.
        self._pool._network_backend = _CheckedNetwork(self._pool._network_backend)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await check_host(request.url.host)
        return await super().handle_async_request(request)
