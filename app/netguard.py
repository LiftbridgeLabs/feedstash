"""Keeps the server's own web requests (feeds, saved pages) away from link-local addresses.

169.254.0.0/16 and fe80::/10 hold cloud metadata services, which hand out credentials to whatever asks from the
machine; a feed or saved link pointed there would have FeedStash fetch them and show the reply. Everything else,
your LAN included, stays reachable: people follow feeds on their own network. The check runs on every request,
redirects included, against the address a host name resolves to.
"""

import asyncio
import ipaddress
import socket

import httpx


class BlockedAddress(httpx.ConnectError):
    """The address is link-local; shown to users as the reason a fetch failed."""


def _blocked(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_link_local


async def check_host(host: str) -> None:
    """Raises BlockedAddress if `host` is, or resolves to, a link-local address."""
    if _blocked(host):
        raise BlockedAddress(f"FeedStash doesn't fetch link-local addresses like {host}")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return  # unresolvable: the request itself will fail with the usual error
    for info in infos:
        if _blocked(info[4][0]):
            raise BlockedAddress(f"FeedStash doesn't fetch link-local addresses ({host} points to one)")


class GuardedTransport(httpx.AsyncHTTPTransport):
    """An HTTP transport that checks each request's host first. Redirects are separate requests, so they're
    checked too."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await check_host(request.url.host)
        return await super().handle_async_request(request)
