"""The server's own fetches never reach link-local addresses (cloud metadata), directly, by name, or by redirect."""

import asyncio
import socket

import httpx
import pytest

from app import netguard
from app.feeds.fetcher import Fetcher, FetchError, create_client


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("host", ["169.254.169.254", "fe80::1", "::ffff:169.254.169.254"])
def test_link_local_addresses_are_refused(host):
    with pytest.raises(netguard.BlockedAddress):
        run(netguard.check_host(host))


@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.20", "10.0.0.5", "93.184.216.34"])
def test_other_addresses_including_the_lan_are_allowed(host):
    run(netguard.check_host(host))


def test_a_name_that_resolves_to_a_link_local_address_is_refused(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(netguard.BlockedAddress, match="points to one"):
        run(netguard.check_host("metadata.example.com"))


def test_following_a_feed_on_a_metadata_address_says_why_it_failed():
    async def follow():
        async with create_client() as client:
            await Fetcher(client).discover("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(FetchError, match="link-local"):
        run(follow())


def test_redirects_are_checked_too(monkeypatch):
    # The first hop is an ordinary address; it redirects to the metadata service. Only the network is faked.
    sent = []

    async def network(self, request):
        sent.append(request.url.host)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", network)

    async def fetch():
        async with httpx.AsyncClient(transport=netguard.GuardedTransport(), follow_redirects=True) as client:
            await client.get("http://93.184.216.34/")

    with pytest.raises(netguard.BlockedAddress):
        run(fetch())
    assert sent == ["93.184.216.34"]  # the redirect was refused before anything was sent to it
