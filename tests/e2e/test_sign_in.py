import re

from support.smtp import FakeSMTP, body

PASSWORD = "correct horse battery"


def fill_and_submit(page, form: str, **fields: str) -> None:
    assignments = "".join(f"f.elements[{name!r}].value = {value!r};" for name, value in fields.items())
    page.js(f"(() => {{ const f = document.querySelector('form[data-login={form}]'); {assignments} f.requestSubmit(); }})()")


def test_first_run_setup_then_sign_out_and_back_in_with_the_password(browser_page, start_server):
    server = start_server(DEV_LOGIN="false")
    page = browser_page
    page.goto(server.base_url + "/")
    assert page.wait_for("!!document.querySelector('form[data-login=setup][data-ready]')")  # login.js is wired up

    fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
    assert page.wait_for("!!window.reader && document.querySelector('#user-name')?.textContent === 'Owner'", timeout=20)

    page.js("location.hash = '#/settings'")
    assert page.wait_for("document.querySelector('[data-account-list]')?.textContent.includes('owner@example.com')")
    page.js("document.querySelector('[data-settings=new-account]').click()")
    assert page.wait_for("!!document.querySelector('dialog[open] input[name=email]')")
    page.js("""(() => {
      const d = document.querySelector('dialog[open]');
      d.querySelector('input[name=email]').value = 'kid@example.com';
      d.querySelector('input[name=password]').value = 'kid password';
      d.querySelector('form').requestSubmit();
    })()""")
    assert page.wait_for("document.querySelector('[data-account-list]').textContent.includes('kid@example.com')")

    page.js("document.querySelector('#logout-btn').click()")
    assert page.wait_for("!!document.querySelector('form[data-login=password][data-ready]')", timeout=10)
    fill_and_submit(page, "password", email="owner@example.com", password=PASSWORD)
    assert page.wait_for("!!window.reader && document.querySelector('#user-name')?.textContent === 'Owner'", timeout=20)
    assert not page.errors, page.errors


def test_an_admin_invites_someone_who_makes_their_own_account(browser_page, start_server):
    server = start_server(DEV_LOGIN="false")
    page = browser_page
    page.goto(server.base_url + "/")
    assert page.wait_for("!!document.querySelector('form[data-login=setup][data-ready]')")
    fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
    assert page.wait_for("!!window.reader", timeout=20)

    page.js("location.hash = '#/settings/admin'")
    assert page.wait_for("!!document.querySelector('[data-settings=invite]') && !document.querySelector('[data-accounts-section]').hidden")
    page.js("document.querySelector('[data-settings=invite]').click()")
    assert page.wait_for("!!document.querySelector('dialog[open] select[name=days]')")
    page.js("""(() => { const d = document.querySelector('dialog[open]');
      d.querySelector('input[name=email]').value = 'ann@example.com'; d.querySelector('form').requestSubmit(); })()""")
    assert page.wait_for("document.querySelector('dialog[open] h2')?.textContent === 'Send this link'")
    link = page.js("document.querySelector('dialog[open] input[readonly]').value")
    assert "/invite#" in link
    # Copy works on a plain-http address too, where browsers leave out navigator.clipboard.
    page.js("Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })")
    page.click("dialog[open] [data-copy]")
    assert page.wait_for("document.querySelector('dialog[open] [data-copy]').textContent === 'Copied'")
    page.js("document.querySelector('dialog[open] [type=submit]').click()")
    assert page.wait_for("document.querySelector('[data-invite-list]').textContent.includes('ann@example.com')")

    page.js("document.querySelector('#logout-btn').click()")
    assert page.wait_for("!!document.querySelector('form[data-login=password][data-ready]')", timeout=10)
    page.goto(link)
    assert page.wait_for("!!document.querySelector('form[data-login=invite][data-ready]:not([hidden])')")
    assert page.js("document.querySelector('form[data-login=invite] [name=email]').value") == "ann@example.com"
    assert page.js("document.querySelector('form[data-login=invite] [name=email]').readOnly") is True
    fill_and_submit(page, "invite", name="Ann", password="ann's password")
    assert page.wait_for("!!window.reader && document.querySelector('#user-name')?.textContent === 'Ann'", timeout=20)

    page.js("document.querySelector('#logout-btn').click()")
    assert page.wait_for("!!document.querySelector('form[data-login=password][data-ready]')", timeout=10)
    page.goto(link)  # used up
    assert page.wait_for("document.querySelector('[data-invite-problem]')?.textContent.includes('has been used')")
    assert page.js("document.querySelector('form[data-login=invite]').hidden") is True
    assert not page.errors, page.errors


def test_forgot_password_sends_a_link_that_sets_a_new_password(browser_page, start_server):
    smtp = FakeSMTP()
    try:
        server = start_server(DEV_LOGIN="false", SMTP_HOST="127.0.0.1", SMTP_PORT=str(smtp.port),
                              SMTP_SECURITY="none", SMTP_FROM="feedstash@example.com")
        page = browser_page
        page.goto(server.base_url + "/")
        assert page.wait_for("!!document.querySelector('form[data-login=setup][data-ready]')")
        fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
        assert page.wait_for("!!window.reader", timeout=20)
        page.js("document.querySelector('#logout-btn').click()")
        assert page.wait_for("!!document.querySelector('form[data-login=password][data-ready]')", timeout=10)

        # "Forgot password?" swaps in the reset form, carrying the email typed so far.
        page.js("document.querySelector('form[data-login=password] [name=email]').value = 'owner@example.com'")
        page.js("document.querySelector('[data-forgot=open]').click()")
        assert page.js("document.querySelector('form[data-login=password]').hidden") is True
        assert page.js("document.querySelector('form[data-login=forgot] [name=email]').value") == "owner@example.com"
        page.js("document.querySelector('form[data-login=forgot]').requestSubmit()")
        assert page.wait_for("!document.querySelector('[data-login-done]').hidden")
        assert "we've sent it a link" in page.js("document.querySelector('[data-login-done]').textContent")
        page.js("document.querySelector('[data-forgot=close]').click()")
        assert page.js("document.querySelector('form[data-login=password]').hidden") is False

        token = re.search(r"/reset#([\w-]+)", body(smtp.wait_for(1)[0])).group(1)
        page.goto(server.base_url + "/reset#" + token)
        assert page.wait_for("!!document.querySelector('form[data-login=reset][data-ready]:not([hidden])')")
        fill_and_submit(page, "reset", password="a brand new passphrase")
        assert page.wait_for("!!window.reader && document.querySelector('#user-name')?.textContent === 'Owner'", timeout=20)

        # The link is used up: opening it again says so instead of showing the form.
        page.goto(server.base_url + "/reset#" + token)
        assert page.wait_for("!document.querySelector('[data-reset-problem]').hidden")
        assert page.js("document.querySelector('form[data-login=reset]').hidden") is True
        assert not page.errors, page.errors
    finally:
        smtp.close()


def test_the_eye_button_shows_and_hides_a_password(browser_page, start_server):
    server = start_server(DEV_LOGIN="false")
    page = browser_page
    page.goto(server.base_url + "/")
    assert page.wait_for("!!document.querySelector('form[data-login=setup] .reveal-btn')")
    field = "document.querySelector('form[data-login=setup] input[name=password]')"
    eye = "document.querySelector('form[data-login=setup] .reveal-btn')"
    assert page.js(f"{field}.type + ' ' + {eye}.getAttribute('aria-label')") == "password Show password"
    assert page.js(f"{field}.autocomplete") == "new-password"  # password managers see the same field
    page.js(f"{eye}.click()")
    assert page.js(f"{field}.type + ' ' + {eye}.getAttribute('aria-label')") == "text Hide password"
    page.js(f"{eye}.click()")
    assert page.js(f"{field}.type") == "password"
    page.js(f"{eye}.click()")
    fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
    assert page.wait_for("!!window.reader", timeout=20)  # sent while shown: it went back to hidden first

    # Fields made later, like Change your password in Settings, get the button too.
    page.js("location.hash = '#/settings/you'")
    assert page.wait_for("!!document.querySelector('[data-settings=change-password]')")
    page.js("document.querySelector('[data-settings=change-password]').click()")
    assert page.wait_for("document.querySelectorAll('dialog[open] .reveal-btn').length === 2")
    page.js("document.querySelector('dialog[open] .reveal-btn').click()")
    assert page.js("document.querySelector('dialog[open] input[name=current]').type") == "text"
    assert not page.errors, page.errors
