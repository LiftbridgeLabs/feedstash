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
