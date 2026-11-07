"""Passkeys in a real browser: Chrome's virtual authenticator stands in for Touch ID or a phone."""

from e2e.test_sign_in import PASSWORD, fill_and_submit


def test_add_a_passkey_in_settings_then_sign_in_with_it(browser_page, start_server):
    server = start_server(DEV_LOGIN="false", BASE_URL="{server},{localhost}")
    local = server.base_url.replace("127.0.0.1", "localhost")  # browsers refuse passkeys at an IP address
    page = browser_page
    page.send("WebAuthn.enable")
    page.send("WebAuthn.addVirtualAuthenticator", options={
        "protocol": "ctap2", "transport": "internal", "hasResidentKey": True, "hasUserVerification": True,
        "isUserVerified": True, "automaticPresenceSimulation": True,
    })
    page.goto(local + "/")
    assert page.wait_for("!!document.querySelector('form[data-login=setup][data-ready]')")
    fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
    assert page.wait_for("!!window.reader && document.querySelector('#user-name')?.textContent === 'Owner'", timeout=20)

    page.js("location.hash = '#/settings/you'")
    assert page.wait_for("!!document.querySelector('[data-passkey-action=add]')")
    page.click("[data-passkey-action=add]")
    assert page.wait_for("!!document.querySelector('dialog[open] input[name=password]')")
    page.js("""(() => {
      const d = document.querySelector('dialog[open]');
      d.querySelector('input[name=name]').value = 'Test laptop';
      d.querySelector('input[name=password]').value = %r;
    })()""" % PASSWORD)
    page.click("dialog[open] [type=submit]")
    assert page.wait_for("document.querySelector('[data-passkey-list]')?.textContent.includes('Test laptop')", timeout=15)

    page.js("document.querySelector('#logout-btn').click()")
    assert page.wait_for("document.querySelector('[data-passkey]')?.dataset.ready === 'true'", timeout=10)
    page.click("[data-passkey]")
    assert page.wait_for("!!window.reader && document.querySelector('#user-name')?.textContent === 'Owner'", timeout=20)
    assert not page.errors, page.errors
