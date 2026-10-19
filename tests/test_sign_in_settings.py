"""Settings → Sign-in: admins add Google or OIDC providers and keep the allowed list, without touching the server's
settings."""

from urllib.parse import parse_qs, urlsplit

import httpx

from support.oidc import CLIENT_ID, CLIENT_SECRET
from test_auth import PASSWORD, client_for, set_up


def add_pocket_id(admin: httpx.Client, issuer: str, **overrides) -> httpx.Response:
    body = {"kind": "oidc", "name": "Pocket ID", "issuer": issuer, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    return admin.post("/api/admin/sign-in/providers", json={**body, **overrides})


def test_an_admin_adds_pocket_id_and_people_on_the_list_sign_in_with_it(start_server, oidc_provider):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},https://feedstash.example.com")
    admin = set_up(server)

    overview = admin.get("/api/admin/sign-in").json()
    # The redirect URI to give the provider is known before anything is saved.
    assert overview["callback_urls"] == [f"{server.base_url}/auth/sso/callback", "https://feedstash.example.com/auth/sso/callback"]
    assert overview["providers"] == [] and overview["password_login"] is True

    response = add_pocket_id(admin, oidc_provider.issuer + "/")
    assert response.status_code == 201, response.text
    (provider,) = response.json()["providers"]
    assert (provider["name"], provider["issuer"], provider["enabled"]) == ("Pocket ID", oidc_provider.issuer, True)
    assert CLIENT_SECRET not in response.text  # the secret never comes back
    key = f"p{provider['id']}"
    assert "Sign in with Pocket ID" in httpx.get(server.base_url + "/").text

    # Sign-ins come back to the one callback address.
    start = httpx.get(f"{server.base_url}/auth/login/{key}")
    assert parse_qs(urlsplit(start.headers["location"]).query)["redirect_uri"] == [f"{server.base_url}/auth/sso/callback"]

    # Nobody is on the allowed list yet.
    oidc_provider.claims = {"sub": "ann-1", "email": "ann@example.com", "email_verified": True, "name": "Ann"}
    refused = client_for(server, follow_redirects=True).get(f"/auth/login/{key}")
    assert refused.url.params.get("error") == "not_allowed"

    listed = admin.put("/api/admin/sign-in/allowed", json={"emails": ["Ann@Example.com"], "domains": ["@family.example"]})
    assert listed.status_code == 200, listed.text
    assert (listed.json()["allowed_emails"], listed.json()["allowed_domains"]) == (["ann@example.com"], ["family.example"])

    ann = client_for(server, follow_redirects=True)
    ann.get(f"/auth/login/{key}")
    assert ann.get("/api/me").json()["email"] == "ann@example.com"
    oidc_provider.claims = {"sub": "cy-1", "email": "cy@family.example", "email_verified": True}
    cy = client_for(server, follow_redirects=True)
    cy.get(f"/auth/login/{key}")
    assert cy.get("/api/me").json()["email"] == "cy@family.example"

    # Taking someone off the list signs them out.
    admin.put("/api/admin/sign-in/allowed", json={"emails": [], "domains": ["family.example"]})
    assert ann.get("/api/me").status_code == 401
    assert cy.get("/api/me").status_code == 200

    # Turned off, the button goes and the address stops working; turned back on, it's back.
    provider_url = f"/api/admin/sign-in/providers/{provider['id']}"
    assert admin.patch(provider_url, json={"enabled": False}).json()["providers"][0]["enabled"] is False
    assert "Sign in with Pocket ID" not in httpx.get(server.base_url + "/").text
    off = httpx.get(f"{server.base_url}/auth/login/{key}")
    assert off.headers["location"] == "/?error=not_configured"
    admin.patch(provider_url, json={"enabled": True, "name": "Home sign-in", "client_secret": ""})
    assert "Sign in with Home sign-in" in httpx.get(server.base_url + "/").text
    oidc_provider.claims = {"sub": "cy-1", "email": "cy@family.example", "email_verified": True}
    again = client_for(server, follow_redirects=True)
    again.get(f"/auth/login/{key}")  # an empty secret kept the saved one
    assert again.get("/api/me").json()["email"] == "cy@family.example"

    assert admin.delete(provider_url).status_code == 204
    assert admin.get("/api/admin/sign-in").json()["providers"] == []
    assert "Home sign-in" not in httpx.get(server.base_url + "/").text


def test_mistakes_are_caught_when_saving(start_server, oidc_provider):
    server = start_server(DEV_LOGIN="false")
    admin = set_up(server)
    for overrides, message in [
        ({"issuer": "id.example.com"}, "has to start with https://"),
        ({"issuer": f"{oidc_provider.issuer}/nothing-here"}, "HTTP 404"),
        ({"issuer": "http://127.0.0.1:9"}, "Couldn't reach"),
        ({"name": "  "}, "Give it a name"),
        ({"scopes": "email profile"}, "have to include openid"),
    ]:
        response = add_pocket_id(admin, **{"issuer": oidc_provider.issuer, **overrides})
        assert response.status_code == 400 and message in response.json()["detail"], (overrides, response.text)
    assert admin.get("/api/admin/sign-in").json()["providers"] == []

    for body, message in [
        ({"emails": ["example.com"]}, "isn't an email address"),
        ({"domains": ["ann@example.com"]}, "isn't a domain"),
    ]:
        response = admin.put("/api/admin/sign-in/allowed", json=body)
        assert response.status_code == 400 and message in response.json()["detail"]

    # Google needs no issuer, and its button always says Google.
    google = admin.post("/api/admin/sign-in/providers", json={
        "kind": "google", "name": "whatever", "client_id": "id.apps.googleusercontent.com", "client_secret": "s",
    })
    assert google.status_code == 201, google.text
    assert google.json()["providers"][0]["name"] == "Google"
    assert "Sign in with Google" in httpx.get(server.base_url + "/").text


def test_only_admins_in_a_browser_can_change_sign_in(start_server, oidc_provider):
    server = start_server(DEV_LOGIN="false")
    admin = set_up(server)
    admin.post("/api/accounts", json={"email": "kid@example.com", "name": "Kid", "password": "kid password"})
    kid = client_for(server)
    assert kid.post("/auth/password", json={"email": "kid@example.com", "password": "kid password"}).status_code == 200
    assert kid.get("/api/admin/sign-in").status_code == 403
    assert add_pocket_id(kid, oidc_provider.issuer).status_code == 403

    token = admin.post("/api/tokens", json={"clientName": "phone"}).json()["token"]
    with_token = httpx.get(server.base_url + "/api/admin/sign-in", headers={"Authorization": f"Bearer {token}"})
    assert with_token.status_code in (401, 403)


def test_an_admin_without_a_password_cant_take_themselves_off_the_list(start_server, oidc_provider):
    server = start_server(DEV_LOGIN="false")
    owner = set_up(server)
    provider = add_pocket_id(owner, oidc_provider.issuer).json()["providers"][0]
    owner.put("/api/admin/sign-in/allowed", json={"emails": ["ann@example.com"]})
    oidc_provider.claims = {"sub": "ann-1", "email": "ann@example.com", "email_verified": True}
    ann = client_for(server, follow_redirects=True)
    ann.get(f"/auth/login/p{provider['id']}")
    ann_id = ann.get("/api/me").json()["id"]
    owner.patch(f"/api/accounts/{ann_id}", json={"is_admin": True})

    response = ann.put("/api/admin/sign-in/allowed", json={"emails": [], "domains": []})
    assert response.status_code == 400 and "would sign you out" in response.json()["detail"]
    assert ann.get("/api/me").status_code == 200
    # The owner has a password to fall back on, so can.
    assert owner.put("/api/admin/sign-in/allowed", json={"emails": []}).status_code == 200
    assert client_for(server).post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 200


def test_providers_from_the_server_settings_are_shown_but_not_changeable(start_server, oidc_provider):
    server = start_server(
        DEV_LOGIN="false", ALLOWED_EMAILS="owner@example.com", OIDC_NAME="Authelia",
        OIDC_ISSUER=oidc_provider.issuer, OIDC_CLIENT_ID=CLIENT_ID, OIDC_CLIENT_SECRET=CLIENT_SECRET,
    )
    admin = set_up(server)
    overview = admin.get("/api/admin/sign-in").json()
    (provider,) = overview["providers"]
    assert (provider["id"], provider["name"], provider["from_server_settings"]) == (None, "Authelia", True)
    assert provider["callback_urls"] == [f"{server.base_url}/auth/oidc/callback"]
    assert overview["server_allowed_emails"] == ["owner@example.com"]
    assert CLIENT_SECRET not in str(overview)


def test_a_provider_pointed_somewhere_else_never_opens_someone_elses_account(start_server, oidc_provider):
    from conftest import free_port
    from support.oidc import FakeOidcProvider

    other = FakeOidcProvider(free_port())
    other.start()
    try:
        server = start_server(DEV_LOGIN="false")
        admin = set_up(server)
        provider = add_pocket_id(admin, oidc_provider.issuer).json()["providers"][0]
        admin.put("/api/admin/sign-in/allowed", json={"emails": ["*"]})
        key = f"p{provider['id']}"

        oidc_provider.claims = {"sub": "1", "email": "ann@example.com", "email_verified": True}
        ann = client_for(server, follow_redirects=True)
        ann.get(f"/auth/login/{key}")
        ann_id = ann.get("/api/me").json()["id"]

        # Subjects are only unique at their issuer: "1" somewhere else is a different person.
        admin.patch(f"/api/admin/sign-in/providers/{provider['id']}", json={"issuer": other.issuer})
        other.claims = {"sub": "1", "email": "mallory@example.com", "email_verified": True}
        mallory = client_for(server, follow_redirects=True)
        mallory.get(f"/auth/login/{key}")
        me = mallory.get("/api/me").json()
        assert me["email"] == "mallory@example.com" and me["id"] != ann_id
        emails = {account["id"]: account["email"] for account in admin.get("/api/accounts").json()}
        assert emails[ann_id] == "ann@example.com"

        # Removing a provider and adding another never brings its address back.
        admin.delete(f"/api/admin/sign-in/providers/{provider['id']}")
        again = add_pocket_id(admin, oidc_provider.issuer).json()["providers"][0]
        assert again["id"] != provider["id"]
    finally:
        other.stop()


def test_one_switch_turns_every_sign_in_button_off_and_back_on(start_server, oidc_provider):
    server = start_server(
        DEV_LOGIN="false", GOOGLE_CLIENT_ID="id.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="secret",
    )
    admin = set_up(server)
    provider = add_pocket_id(admin, oidc_provider.issuer).json()["providers"][-1]
    page = httpx.get(server.base_url + "/").text
    assert "Sign in with Google" in page and "Sign in with Pocket ID" in page

    off = admin.put("/api/admin/sign-in/switch", json={"enabled": False})
    assert off.status_code == 200 and off.json()["sso_enabled"] is False
    page = httpx.get(server.base_url + "/").text
    assert "Sign in with" not in page and 'name="password"' in page
    assert httpx.get(f"{server.base_url}/auth/login/p{provider['id']}").headers["location"] == "/?error=not_configured"
    assert len(off.json()["providers"]) == 2  # still set up, just hidden

    admin.put("/api/admin/sign-in/switch", json={"enabled": True})
    assert "Sign in with Pocket ID" in httpx.get(server.base_url + "/").text

    # A provider from the server's settings can be turned off here too, though not changed.
    google = admin.patch("/api/admin/sign-in/server/google", json={"enabled": False}).json()["providers"][0]
    assert (google["key"], google["enabled"]) == ("google", False)
    page = httpx.get(server.base_url + "/").text
    assert "Sign in with Google" not in page and "Sign in with Pocket ID" in page
    admin.patch("/api/admin/sign-in/server/google", json={"enabled": True})
    assert "Sign in with Google" in httpx.get(server.base_url + "/").text
    assert admin.patch("/api/admin/sign-in/server/p1", json={"enabled": False}).status_code == 404


def test_with_passwords_off_the_last_way_in_cant_be_turned_off(start_server, oidc_provider):
    server = start_server(
        DEV_LOGIN="false", PASSWORD_LOGIN="false", ALLOWED_EMAILS="ann@example.com",
        OIDC_ISSUER=oidc_provider.issuer, OIDC_CLIENT_ID=CLIENT_ID, OIDC_CLIENT_SECRET=CLIENT_SECRET,
    )
    oidc_provider.claims = {"sub": "ann-1", "email": "ann@example.com", "email_verified": True}
    admin = client_for(server, follow_redirects=True)
    admin.get("/auth/login")

    for response in (
        admin.put("/api/admin/sign-in/switch", json={"enabled": False}),
        admin.patch("/api/admin/sign-in/server/oidc", json={"enabled": False}),
    ):
        assert response.status_code == 400 and "nobody a way to sign in" in response.json()["detail"]

    # With a second one on, either can go.
    second = add_pocket_id(admin, oidc_provider.issuer).json()["providers"][-1]
    assert admin.patch("/api/admin/sign-in/server/oidc", json={"enabled": False}).status_code == 200
    blocked = admin.delete(f"/api/admin/sign-in/providers/{second['id']}")
    assert blocked.status_code == 400 and "nobody a way to sign in" in blocked.json()["detail"]


def test_buttons_take_an_icon_and_a_color(start_server, oidc_provider):
    server = start_server(DEV_LOGIN="false")
    admin = set_up(server)
    response = add_pocket_id(admin, oidc_provider.issuer, icon="shield", color="#1E3A8A")
    provider = response.json()["providers"][0]
    assert (provider["icon"], provider["color"]) == ("shield", "#1e3a8a")
    page = httpx.get(server.base_url + "/").text
    assert "/static/sso/shield.svg" in page and "--sso-bg: #1e3a8a; --sso-fg: #ffffff" in page

    logo = "https://id.example.com/api/application-configuration/logo"
    admin.patch(f"/api/admin/sign-in/providers/{provider['id']}", json={"icon": logo, "color": ""})
    page = httpx.get(server.base_url + "/").text
    assert f'<img src="{logo}"' in page and "--sso-bg" not in page

    for body, message in [
        ({"icon": "javascript:alert(1)"}, "built-in ones"),
        ({"icon": 'https://x.example.com/a.png" onerror="x'}, "built-in ones"),
        ({"color": "blue"}, "look like #3355ff"),
    ]:
        bad = admin.patch(f"/api/admin/sign-in/providers/{provider['id']}", json=body)
        assert bad.status_code == 400 and message in bad.json()["detail"], body

    google = admin.post("/api/admin/sign-in/providers", json={
        "kind": "google", "client_id": "id.apps.googleusercontent.com", "client_secret": "s", "color": "#ff0000",
    })
    assert google.status_code == 201
    page = httpx.get(server.base_url + "/").text
    assert 'class="btn btn-lg sso-btn sso-google"' in page and "/static/sso/google.svg" in page
