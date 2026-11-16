"""The server's own fetches never reach link-local addresses (cloud metadata), directly, by name, or by redirect."""

import asyncio
import socket

import httpcore
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


@pytest.mark.parametrize("host", ["100.100.100.200", "fd00:ec2::254"])
def test_other_clouds_metadata_addresses_are_refused(host):
    with pytest.raises(netguard.BlockedAddress):
        run(netguard.check_host(host))


def test_the_connection_uses_the_address_checked_at_that_moment(monkeypatch):
    # DNS rebinding: the name looks ordinary when the request is checked, then points at the metadata service when
    # the connection resolves it. The connection resolves it once itself and refuses.
    answers = iter(["93.184.216.34", "169.254.169.254"])
    connected = []

    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (next(answers), 0))]

    class Recorder(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **kwargs):
            connected.append(host)
            raise httpcore.ConnectError("not really connecting")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)

    async def fetch():
        transport = netguard.GuardedTransport()
        transport._pool._network_backend._inner = Recorder()
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("http://rebind.example.com/feed")

    with pytest.raises(netguard.BlockedAddress, match="points to one"):
        run(fetch())
    assert connected == []


def test_the_connection_goes_to_the_resolved_address(monkeypatch):
    connected = []

    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    class Recorder(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **kwargs):
            connected.append((host, port))
            raise httpcore.ConnectError("not really connecting")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)

    async def fetch():
        transport = netguard.GuardedTransport()
        transport._pool._network_backend._inner = Recorder()
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("http://feeds.example.com/feed")

    with pytest.raises(httpx.ConnectError):
        run(fetch())
    assert connected == [("93.184.216.34", 80)]


# FETCH_PUBLIC_ONLY: for a server whose accounts belong to people who shouldn't reach the network it sits on.


@pytest.fixture
def public_only(monkeypatch):
    monkeypatch.setattr(netguard, "_public_only", True)


@pytest.mark.parametrize("host", [
    "127.0.0.1", "::1", "10.0.0.5", "172.17.0.1", "192.168.1.20", "100.64.0.9", "fd12:3456::1", "0.0.0.0",
    "::ffff:10.0.0.5", "169.254.169.254",
])
def test_public_only_refuses_every_address_that_is_not_on_the_internet(public_only, host):
    with pytest.raises(netguard.BlockedAddress):
        run(netguard.check_host(host))


@pytest.mark.parametrize("host", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_only_still_fetches_public_addresses(public_only, host):
    run(netguard.check_host(host))


def test_public_only_refuses_a_name_that_points_inside(public_only, monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("172.17.0.1", 0))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(netguard.BlockedAddress, match="only fetches public addresses"):
        run(netguard.check_host("inside.example.com"))


def test_public_only_says_why_following_a_feed_on_the_machine_itself_failed(public_only):
    async def follow():
        async with create_client() as client:
            await Fetcher(client).discover("http://127.0.0.1:8672/api/health")

    with pytest.raises(FetchError, match="only fetches public addresses"):
        run(follow())


def test_public_only_checks_the_address_connected_to_not_only_the_name(public_only, monkeypatch):
    # The name passes the first look and points inside by the time of the connection (DNS rebinding).
    answers = iter([[("93.184.216.34", 0)], [("10.0.0.5", 0)]])

    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", address) for address in next(answers)]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)

    async def fetch():
        async with httpx.AsyncClient(transport=netguard.GuardedTransport()) as client:
            await client.get("http://rebind.example.com/")

    with pytest.raises(netguard.BlockedAddress, match="points to a private one"):
        run(fetch())


def test_a_mailbox_on_the_inside_is_refused_before_anything_connects(public_only, monkeypatch):
    from app.mail.imap import Mailbox, MailboxConfig, MailError

    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", port))])
    connected = []
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: connected.append(args))
    with pytest.raises(MailError, match="only connects to public addresses"):
        Mailbox(MailboxConfig(host="mail.inside.example.com", port=993, username="u", password="p")).__enter__()
    assert connected == []


def test_public_only_reaches_a_public_mailbox_at_the_checked_address_and_checks_its_certificate(public_only, monkeypatch):
    import ssl

    from app.mail.imap import Mailbox, MailboxConfig, MailError

    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", port))])
    connected, wrapped = [], {}
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout=None: connected.append(address) or object())

    def wrap(self, sock, server_hostname=None, **kwargs):
        wrapped.update(name=server_hostname, verify=self.verify_mode, check=self.check_hostname)
        raise OSError("stop here")

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    with pytest.raises(MailError, match="Couldn't reach"):
        Mailbox(MailboxConfig(host="mail.example.com", port=993, username="u", password="p")).__enter__()
    assert connected == [("93.184.216.34", 993)]  # the address that was checked, not the name again
    assert wrapped == {"name": "mail.example.com", "verify": ssl.CERT_REQUIRED, "check": True}


def test_public_only_refuses_a_public_address_this_machine_holds(public_only, monkeypatch):
    # A server with a public address of its own: the range says "internet", but it is the machine itself.
    monkeypatch.setattr(netguard, "_is_own", lambda address: address == "203.0.113.7")
    with pytest.raises(netguard.BlockedAddress):
        run(netguard.check_host("203.0.113.7"))
    run(netguard.check_host("93.184.216.34"))


def test_an_address_of_this_machine_is_recognized_and_one_elsewhere_is_not():
    netguard._is_own.cache_clear()
    assert netguard._is_own("127.0.0.1") is True
    assert netguard._is_own("93.184.216.34") is False


def test_refused_addresses_and_networks_are_never_fetched_whatever_else_is_set(monkeypatch):
    monkeypatch.setattr(netguard, "_refused", netguard.parse_refused("203.0.113.7, 2001:db8::/48 198.51.100.0/24"))
    for host in ("203.0.113.7", "2001:db8::1", "198.51.100.200"):
        with pytest.raises(netguard.BlockedAddress, match="doesn't fetch"):
            run(netguard.check_host(host))
    run(netguard.check_host("203.0.113.8"))
    run(netguard.check_host("192.168.1.20"))  # the LAN stays reachable without FETCH_PUBLIC_ONLY


def test_a_refused_list_that_is_not_addresses_stops_the_server_starting_with_a_reason():
    from pydantic import ValidationError

    from app.settings import Settings

    with pytest.raises(ValidationError, match="FETCH_REFUSE takes addresses or networks"):
        Settings(secret_key="x" * 40, fetch_refuse="not-an-address")
