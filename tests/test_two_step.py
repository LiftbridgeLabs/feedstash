"""Two-step sign-in: turning it on, signing in with a code or a recovery code, reset links, and turning it off."""

import time

import pytest

from app import totp
from support.smtp import FakeSMTP
from test_auth import PASSWORD, client_for, set_up
from test_email import mail_env, reset_token

EMAIL = "owner@example.com"


@pytest.fixture
def smtp():
    fake = FakeSMTP()
    yield fake
    fake.close()


def next_code(secret: str, offset: int = 1) -> str:
    """A code the server takes as new: the confirm step used the current one, and each works once."""
    return totp.code_at(secret, totp.step_of(time.time()) + offset)


def turn_on(client) -> tuple[str, list[str]]:
    setup = client.post("/api/account/two-step/start", json={"password": PASSWORD})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["uri"].startswith("otpauth://totp/FeedStash:") and "<svg" in setup.json()["svg"]
    confirmed = client.post("/api/account/two-step/confirm", json={"code": totp.code_at(secret, totp.step_of(time.time()))})
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


def password_step(server, email: str = EMAIL):
    client = client_for(server)
    answer = client.post("/auth/password", json={"email": email, "password": PASSWORD})
    assert answer.status_code == 200, answer.text
    return client, answer.json()


def test_turning_it_on_asks_for_the_password_and_a_right_first_code(start_server):
    owner = set_up(start_server(DEV_LOGIN="false"))
    assert owner.get("/api/account/two-step").json() == {"enabled": False, "recovery_codes_left": 0, "available": True}
    wrong = owner.post("/api/account/two-step/start", json={"password": "not it"})
    assert wrong.status_code == 400 and "password isn't right" in wrong.json()["detail"]
    owner.post("/api/account/two-step/start", json={"password": PASSWORD})
    bad = owner.post("/api/account/two-step/confirm", json={"code": "000000"})
    assert bad.status_code == 400 and "code isn't right" in bad.json()["detail"]
    assert owner.get("/api/account/two-step").json()["enabled"] is False
    secret, codes = turn_on(owner)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert owner.get("/api/account/two-step").json() == {"enabled": True, "recovery_codes_left": 10, "available": True}
    assert owner.get("/api/me").status_code == 200  # this browser stays signed in
    again = owner.post("/api/account/two-step/start", json={"password": PASSWORD})
    assert again.status_code == 409


def test_signing_in_needs_the_code_after_the_password(start_server):
    server = start_server(DEV_LOGIN="false")
    owner = set_up(server)
    elsewhere, _ = password_step(server)
    assert elsewhere.get("/api/me").status_code == 200
    secret, _ = turn_on(owner)
    assert elsewhere.get("/api/me").status_code == 401  # turning it on signed other browsers out

    client, answer = password_step(server)
    assert answer == {"ok": True, "two_step": True}
    assert client.get("/api/me").status_code == 401  # a right password alone isn't signed in
    wrong = client.post("/auth/two-step", json={"code": "123456"})
    assert wrong.status_code == 401 and "isn't right" in wrong.json()["detail"]
    code = next_code(secret)
    assert client.post("/auth/two-step", json={"code": code}).status_code == 200
    assert client.get("/api/me").json()["email"] == EMAIL

    replay, _ = password_step(server)
    assert replay.post("/auth/two-step", json={"code": code}).status_code == 401  # each code works once
    assert client_for(server).post("/auth/two-step", json={"code": next_code(secret, 0)}).status_code == 401  # no password first


def test_a_recovery_code_works_once(start_server):
    server = start_server(DEV_LOGIN="false")
    owner = set_up(server)
    _, codes = turn_on(owner)
    client, _ = password_step(server)
    assert client.post("/auth/two-step", json={"code": codes[0].upper().replace("-", " ")}).status_code == 200
    assert owner.get("/api/account/two-step").json()["recovery_codes_left"] == 9
    again, _ = password_step(server)
    assert again.post("/auth/two-step", json={"code": codes[0]}).status_code == 401
    fresh = owner.post("/api/account/two-step/recovery-codes", json={"password": PASSWORD}).json()["recovery_codes"]
    assert again.post("/auth/two-step", json={"code": codes[1]}).status_code == 401  # replaced by the new ones
    assert again.post("/auth/two-step", json={"code": fresh[0]}).status_code == 200


def test_wrong_codes_count_toward_the_sign_in_limit(start_server):
    server = start_server(DEV_LOGIN="false")
    owner = set_up(server)
    secret, _ = turn_on(owner)
    client, _ = password_step(server)
    answers = [client.post("/auth/two-step", json={"code": "000000"}).status_code for _ in range(11)]
    assert answers[-1] == 429
    assert client.post("/auth/two-step", json={"code": next_code(secret)}).status_code == 429


def test_a_reset_link_still_asks_for_the_code(start_server, smtp):
    server = start_server(**mail_env(smtp))
    owner = set_up(server)
    secret, _ = turn_on(owner)
    client = client_for(server)
    client.post("/auth/forgot", json={"email": EMAIL})
    reset = client.post("/auth/reset", json={"token": reset_token(smtp.wait_for(1)[0]), "password": "a whole new one"})
    assert reset.status_code == 200 and reset.json()["two_step"] is True
    assert client.get("/api/me").status_code == 401
    assert client.post("/auth/two-step", json={"code": next_code(secret)}).status_code == 200
    assert client.get("/api/me").status_code == 200


def test_turning_it_off_yourself_or_by_an_admin(start_server):
    server = start_server(DEV_LOGIN="false")
    owner = set_up(server)
    owner.post("/api/accounts", json={"email": "kid@example.com", "password": PASSWORD})
    kid, _ = password_step(server, "kid@example.com")
    turn_on(kid)
    kid_id = next(a["id"] for a in owner.get("/api/accounts").json() if a["email"] == "kid@example.com")
    assert next(a for a in owner.get("/api/accounts").json() if a["id"] == kid_id)["two_step"] is True
    assert kid.post(f"/api/accounts/{kid_id}/two-step/off").status_code == 403  # admins only
    assert owner.post(f"/api/accounts/{kid_id}/two-step/off").status_code == 200
    assert kid.get("/api/me").status_code == 401  # signed out everywhere, in case someone else has the phone
    _, answer = password_step(server, "kid@example.com")
    assert answer["two_step"] is False
    assert owner.post(f"/api/accounts/{kid_id}/two-step/off").status_code == 404

    turn_on(owner)
    me = owner.get("/api/me").json()["id"]
    assert owner.post(f"/api/accounts/{me}/two-step/off").status_code == 400
    wrong = owner.post("/api/account/two-step/off", json={"password": "nope"})
    assert wrong.status_code == 400
    assert owner.post("/api/account/two-step/off", json={"password": PASSWORD}).status_code == 200
    assert password_step(server)[1]["two_step"] is False


def test_accounts_without_a_password_dont_get_it(start_server):
    api = start_server().login()  # the dev sign-in has no password
    assert api.get("/api/account/two-step").json()["available"] is False
    refused = api.post("/api/account/two-step/start", json={"password": ""})
    assert refused.status_code == 400 and "Google and single sign-on have their own" in refused.json()["detail"]
