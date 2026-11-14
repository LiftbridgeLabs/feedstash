"""Passkeys: adding one in Settings → You, signing in with it, and what's refused."""

import time

import httpx

from app import totp
from conftest import CSRF_HEADERS
from support.passkey import SoftPasskey
from test_auth import PASSWORD, client_for


def local(server) -> str:
    return server.base_url.replace("127.0.0.1", "localhost")


def browser(server) -> httpx.Client:
    """A client at the server's localhost address, where passkeys are allowed."""
    return httpx.Client(base_url=local(server), headers=CSRF_HEADERS, timeout=30)


def owner(server) -> httpx.Client:
    client = browser(server)
    response = client.post("/auth/setup", json={"email": "owner@example.com", "name": "Owner", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


def add(client: httpx.Client, passkey: SoftPasskey, *, name: str = "Mac", password: str = PASSWORD) -> httpx.Response:
    options = client.post("/api/account/passkeys/options").json()["options"]
    return client.post("/api/account/passkeys",
                       json={"name": name, "password": password, "credential": passkey.create(options)})


def sign_in(client: httpx.Client, passkey: SoftPasskey, **kwargs) -> httpx.Response:
    options = client.post("/auth/passkey/options").json()["options"]
    return client.post("/auth/passkey", json={"credential": passkey.get(options, **kwargs)})


def test_add_a_passkey_then_sign_in_with_it_alone(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    me = owner(server)
    passkey = SoftPasskey(local(server))
    assert "data-passkey" not in httpx.get(local(server) + "/").text  # nobody has one yet
    assert add(me, passkey, password="not my password").status_code == 400
    added = add(me, passkey, name="  Jason's   MacBook  ")
    assert added.status_code == 201, added.text
    assert added.json()["name"] == "Jason's MacBook" and added.json()["last_used_at"] is None
    listed = me.get("/api/account/passkeys").json()
    assert listed["available"] is True and [p["name"] for p in listed["passkeys"]] == ["Jason's MacBook"]

    stranger = browser(server)
    assert "data-passkey" in stranger.get("/").text  # the sign-in page offers passkeys now
    assert stranger.get("/api/me").status_code == 401
    signed_in = sign_in(stranger, passkey)
    assert signed_in.status_code == 200, signed_in.text
    assert stranger.get("/api/me").json()["email"] == "owner@example.com"
    assert me.get("/api/account/passkeys").json()["passkeys"][0]["last_used_at"] is not None


def test_a_passkey_answer_works_once_and_only_for_this_server(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    me = owner(server)
    passkey = SoftPasskey(local(server))
    assert add(me, passkey).status_code == 201
    client = browser(server)
    options = client.post("/auth/passkey/options").json()["options"]
    answer = passkey.get(options)
    assert client.post("/auth/passkey", json={"credential": answer}).status_code == 200
    replayed = browser(server).post("/auth/passkey", json={"credential": answer})
    assert replayed.status_code == 401  # no challenge waiting in that browser
    # Nor with a copy of the cookie from before it was used, which still holds the challenge: the server remembers
    # that it's been used. (Phones' passkeys don't count their uses, so nothing else would catch this.)
    thief, victim = browser(server), browser(server)
    options = victim.post("/auth/passkey/options").json()["options"]
    thief.cookies.update(dict(victim.cookies))
    answer = passkey.get(options)
    assert victim.post("/auth/passkey", json={"credential": answer}).status_code == 200
    stolen = thief.post("/auth/passkey", json={"credential": answer})
    assert stolen.status_code == 401 and thief.get("/api/me").status_code == 401
    # Signed for another site (a look-alike phishing page): refused.
    phished = sign_in(browser(server), passkey, origin="https://feedstash.example.net")
    assert phished.status_code == 401 and "couldn't be checked" in phished.json()["detail"]
    # A passkey this server never saw.
    unknown = sign_in(browser(server), SoftPasskey(local(server)))
    assert unknown.status_code == 401 and "isn't set up on this server" in unknown.json()["detail"]
    # Nonsense instead of an answer is refused like any wrong one, not a server error.
    for nonsense in ({}, {"rawId": answer["rawId"], "response": "x"}, {"rawId": 5}):
        mangled = browser(server)
        mangled.post("/auth/passkey/options")
        assert mangled.post("/auth/passkey", json={"credential": nonsense}).status_code == 401, nonsense
    # A passkey made for a look-alike site can't be added either, and the reason is plain.
    options = me.post("/api/account/passkeys/options").json()["options"]
    wrong_site = SoftPasskey(local(server)).create(options, origin="https://feedstash.example.net")
    refused = me.post("/api/account/passkeys", json={"password": PASSWORD, "credential": wrong_site})
    assert refused.status_code == 400 and refused.json()["detail"] == (
        "That passkey couldn't be added. Try again, or try another device.")


def test_adding_the_same_options_twice_or_without_asking_first_is_refused(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    me = owner(server)
    passkey = SoftPasskey(local(server))
    options = me.post("/api/account/passkeys/options").json()["options"]
    answer = passkey.create(options)
    assert me.post("/api/account/passkeys", json={"password": PASSWORD, "credential": answer}).status_code == 201
    again = me.post("/api/account/passkeys", json={"password": PASSWORD, "credential": answer})
    assert again.status_code == 400 and "took too long" in again.json()["detail"]
    # The next add knows the device already has one, so the browser can say so.
    options = me.post("/api/account/passkeys/options").json()["options"]
    assert [c["id"] for c in options["excludeCredentials"]] == [answer["id"]]
    assert options["authenticatorSelection"]["userVerification"] == "required"


def test_two_first_passkeys_started_at_once_dont_leave_one_that_cant_sign_in(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    laptop = owner(server)
    phone = browser(server)
    assert phone.post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 200
    # Both ask before either has finished, so each device is told a different handle for the account.
    first, second = SoftPasskey(local(server)), SoftPasskey(local(server))
    laptop_options = laptop.post("/api/account/passkeys/options").json()["options"]
    phone_options = phone.post("/api/account/passkeys/options").json()["options"]
    assert laptop_options["user"]["id"] != phone_options["user"]["id"]
    added = laptop.post("/api/account/passkeys", json={"password": PASSWORD, "credential": first.create(laptop_options)})
    assert added.status_code == 201
    late = phone.post("/api/account/passkeys", json={"password": PASSWORD, "credential": second.create(phone_options)})
    assert late.status_code == 400 and "add it again" in late.json()["detail"]
    # Made again, it's given the account's handle and signs in.
    assert add(phone, second).status_code == 201
    assert sign_in(browser(server), second).status_code == 200
    assert sign_in(browser(server), first).status_code == 200


def test_rename_and_remove_and_only_your_own(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    me = owner(server)
    passkey = SoftPasskey(local(server))
    passkey_id = add(me, passkey).json()["id"]
    assert me.post("/api/accounts", json={"email": "kid@example.com", "password": PASSWORD}).status_code == 201
    kid = browser(server)
    assert kid.post("/auth/password", json={"email": "kid@example.com", "password": PASSWORD}).status_code == 200
    assert kid.patch(f"/api/account/passkeys/{passkey_id}", json={"name": "Mine now"}).status_code == 404
    assert kid.delete(f"/api/account/passkeys/{passkey_id}").status_code == 404
    assert me.patch(f"/api/account/passkeys/{passkey_id}", json={"name": "iPhone"}).status_code == 200
    assert me.get("/api/account/passkeys").json()["passkeys"][0]["name"] == "iPhone"
    assert me.delete(f"/api/account/passkeys/{passkey_id}").status_code == 200
    removed = sign_in(browser(server), passkey)
    assert removed.status_code == 401 and "may have been removed" in removed.json()["detail"]


def test_a_passkey_skips_the_two_step_code(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    me = owner(server)
    setup = me.post("/api/account/two-step/start", json={"password": PASSWORD}).json()
    assert me.post("/api/account/two-step/confirm", json={"code": totp.code_at(setup["secret"], totp.step_of(int(time.time())))}).status_code == 200
    passkey = SoftPasskey(local(server))
    assert add(me, passkey).status_code == 201
    client = browser(server)
    assert client.post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD}).json()["two_step"]
    client = browser(server)
    assert sign_in(client, passkey).status_code == 200
    assert client.get("/api/me").json()["email"] == "owner@example.com"


def test_no_passkeys_at_an_ip_address_or_plain_http(start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    client_for(server).post("/auth/setup", json={"email": "owner@example.com", "password": PASSWORD})
    at_ip = client_for(server)
    assert at_ip.post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 200
    listed = at_ip.get("/api/account/passkeys").json()
    assert listed["available"] is False and "https" in listed["reason"]
    assert at_ip.post("/api/account/passkeys/options").status_code == 400
    assert at_ip.post("/auth/passkey/options").status_code == 404
    # A LAN address over http, with an https address alongside: points at the https one.
    lan = start_server(DEV_LOGIN="false", BASE_URL="{server},https://feedstash.example.com")
    response = client_for(lan).post("/auth/passkey/options")
    assert response.status_code == 404 and "https://feedstash.example.com" in response.json()["detail"]
