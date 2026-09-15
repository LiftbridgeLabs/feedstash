import httpx

from conftest import CSRF_HEADERS
from support.oidc import CLIENT_ID, CLIENT_SECRET

PASSWORD = "correct horse battery"


def client_for(server, **kwargs) -> httpx.Client:
    return httpx.Client(base_url=server.base_url, headers=CSRF_HEADERS, timeout=30, **kwargs)


def set_up(server, email: str = "owner@example.com") -> httpx.Client:
    client = client_for(server)
    response = client.post("/auth/setup", json={"email": email, "name": "Owner", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


def test_anonymous_visitors_get_the_login_page_with_security_headers(server):
    response = httpx.get(server.base_url + "/")
    assert "Continue as local user" in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_api_requires_sign_in(server):
    assert httpx.get(server.base_url + "/api/tree").status_code == 401


def test_state_changes_require_the_csrf_header(server):
    assert httpx.post(server.base_url + "/api/folders", json={"name": "x"}).status_code == 403


def test_dev_login_then_logout(api):
    assert 'id="articles"' in api.get("/").text
    assert api.get("/api/me").json()["email"] == "dev@localhost"
    assert api.post("/auth/logout").status_code == 200
    assert api.get("/api/tree").status_code == 401


def test_first_run_setup_creates_an_admin_who_then_signs_in_with_a_password(start_server):
    server = start_server(DEV_LOGIN="false")
    assert 'data-login="setup"' in httpx.get(server.base_url + "/").text
    client = client_for(server)
    assert client.post("/auth/setup", json={"email": "owner@example.com", "password": "short"}).status_code == 400
    assert client.post("/auth/setup", json={"email": "Owner@Example.com", "name": "Owner", "password": PASSWORD}).status_code == 200
    me = client.get("/api/me").json()
    assert (me["email"], me["is_admin"], me["has_password"]) == ("owner@example.com", True, True)
    assert client.post("/auth/setup", json={"email": "late@example.com", "password": PASSWORD}).status_code == 409

    page = httpx.get(server.base_url + "/").text
    assert 'data-login="password"' in page and 'data-login="setup"' not in page
    visitor = client_for(server)
    assert visitor.post("/auth/password", json={"email": "owner@example.com", "password": "wrong password"}).status_code == 401
    assert visitor.get("/api/tree").status_code == 401
    assert visitor.post("/auth/password", json={"email": " OWNER@example.com", "password": PASSWORD}).status_code == 200
    assert visitor.get("/api/tree").status_code == 200


def test_setup_must_use_an_allowed_email_when_there_is_an_allowlist(start_server):
    server = start_server(DEV_LOGIN="false", ALLOWED_EMAILS="me@example.com")
    client = client_for(server)
    assert client.post("/auth/setup", json={"email": "intruder@example.com", "password": PASSWORD}).status_code == 403
    assert client.post("/auth/setup", json={"email": "me@example.com", "password": PASSWORD}).status_code == 200


def test_repeated_wrong_passwords_lock_the_account_for_a_while(start_server):
    server = start_server(DEV_LOGIN="false")
    set_up(server)
    guesser = client_for(server)
    codes = [
        guesser.post("/auth/password", json={"email": "owner@example.com", "password": f"guess {i}"}).status_code
        for i in range(11)
    ]
    assert codes == [401] * 10 + [429]
    locked = guesser.post("/auth/password", json={"email": "owner@example.com", "password": PASSWORD})
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0


def test_admins_manage_accounts_and_people_change_their_own_password(start_server):
    server = start_server(DEV_LOGIN="false")
    admin = set_up(server)
    created = admin.post("/api/accounts", json={"email": "kid@example.com", "name": "Kid", "password": "kid password"})
    assert created.status_code == 201, created.text
    kid_id = created.json()["id"]
    assert created.json()["sign_in"] == "password" and not created.json()["is_admin"]
    assert admin.post("/api/accounts", json={"email": "KID@example.com", "password": "kid password"}).status_code == 409

    kid = client_for(server)
    assert kid.post("/auth/password", json={"email": "kid@example.com", "password": "kid password"}).status_code == 200
    assert kid.get("/api/accounts").status_code == 403
    wrong = kid.post("/api/account/password", json={"current_password": "nope", "new_password": "new kid password"})
    assert wrong.status_code == 400
    right = kid.post("/api/account/password", json={"current_password": "kid password", "new_password": "new kid password"})
    assert right.status_code == 200

    assert admin.patch(f"/api/accounts/{kid_id}", json={"password": "reset by admin"}).status_code == 200
    again = client_for(server).post("/auth/password", json={"email": "kid@example.com", "password": "reset by admin"})
    assert again.status_code == 200

    owner_id = admin.get("/api/me").json()["id"]
    assert admin.patch(f"/api/accounts/{owner_id}", json={"is_admin": False}).status_code == 400  # the only admin
    assert admin.delete(f"/api/accounts/{owner_id}").status_code == 400
    token = admin.post("/api/tokens", json={"clientName": "phone"}).json()["token"]
    with_token = httpx.get(server.base_url + "/api/accounts", headers={"Authorization": f"Bearer {token}"})
    assert with_token.status_code == 403

    assert admin.delete(f"/api/accounts/{kid_id}").status_code == 204
    assert kid.get("/api/tree").status_code == 401
    assert [account["email"] for account in admin.get("/api/accounts").json()] == ["owner@example.com"]


def test_sign_in_with_an_openid_connect_provider(start_server, oidc_provider):
    server = start_server(
        DEV_LOGIN="false", PASSWORD_LOGIN="false", ALLOWED_EMAILS="ann@example.com", OIDC_NAME="Pocket ID",
        OIDC_ISSUER=oidc_provider.issuer, OIDC_CLIENT_ID=CLIENT_ID, OIDC_CLIENT_SECRET=CLIENT_SECRET,
    )
    assert "Sign in with Pocket ID" in httpx.get(server.base_url + "/").text

    ann = client_for(server, follow_redirects=True)
    oidc_provider.claims = {"sub": "ann-1", "email": "Ann@Example.com", "email_verified": True, "name": "Ann"}
    assert 'id="articles"' in ann.get("/auth/login").text  # the only sign-in method, so this goes straight to it
    me = ann.get("/api/me").json()
    assert (me["email"], me["name"], me["is_admin"], me["has_password"]) == ("ann@example.com", "Ann", True, False)

    for claims, error in [
        ({"sub": "bob-1", "email": "bob@example.com", "email_verified": True}, "not_allowed"),
        ({"sub": "ann-2", "email": "ann@example.com", "email_verified": False}, "unverified"),
        ({"sub": "ann-3"}, "unverified"),
    ]:
        oidc_provider.claims = claims
        response = client_for(server, follow_redirects=True).get("/auth/login/oidc")
        assert response.url.params.get("error") == error, (claims, str(response.url))


def test_unconfigured_providers_and_turned_off_passwords(start_server):
    server = start_server(DEV_LOGIN="false", PASSWORD_LOGIN="false")
    response = httpx.get(server.base_url + "/auth/login/google")
    assert response.status_code == 303 and response.headers["location"] == "/?error=not_configured"
    assert "No sign-in method is turned on" in httpx.get(server.base_url + "/").text
    assert client_for(server).post("/auth/password", json={"email": "a@example.com", "password": PASSWORD}).status_code == 404
