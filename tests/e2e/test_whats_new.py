"""After an update, an admin is shown what changed, once."""

import time

from e2e.test_sign_in import PASSWORD, fill_and_submit

SIGNED_IN = "!!window.reader && document.querySelector('#user-name')?.textContent === 'Owner'"


def test_an_admin_sees_the_notes_once_after_an_update(browser_page, start_server, tmp_path):
    db_path = tmp_path / "whats-new.db"
    page = browser_page
    first = start_server(db_path=db_path, DEV_LOGIN="false", FEEDSTASH_VERSION="0.6.0")
    page.goto(first.base_url + "/")
    assert page.wait_for("!!document.querySelector('form[data-login=setup][data-ready]')")
    fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
    assert page.wait_for(SIGNED_IN, timeout=20)
    time.sleep(1)
    assert page.js("!document.querySelector('dialog.whats-new')"), "a new server has nothing to announce"
    first.stop()

    updated = start_server(db_path=db_path, DEV_LOGIN="false", FEEDSTASH_VERSION="0.6.1")
    page.goto(updated.base_url + "/")  # still signed in: same database and key, and cookies ignore the port
    assert page.wait_for("!!document.querySelector('dialog.whats-new[open]')", timeout=20)
    assert "What's new in FeedStash 0.6.1" in page.js("document.querySelector('dialog.whats-new h2').textContent")
    assert page.js("document.querySelectorAll('dialog.whats-new li').length") >= 1
    assert page.js("document.querySelector('#app-version').textContent") == "v0.6.1"

    page.js("document.querySelector('dialog.whats-new .btn-primary').click()")
    assert page.wait_for("!document.querySelector('dialog.whats-new')")
    time.sleep(0.5)  # the "seen" request
    page.goto(updated.base_url + "/")
    assert page.wait_for(SIGNED_IN, timeout=20)
    time.sleep(1)
    assert page.js("!document.querySelector('dialog.whats-new')")
    assert not page.errors, page.errors


def test_the_develop_image_shows_which_build_it_is(browser_page, start_server):
    page = browser_page
    server = start_server(DEV_LOGIN="false", FEEDSTASH_VERSION="develop-1a2b3c4")
    page.goto(server.base_url + "/")
    assert page.wait_for("!!document.querySelector('form[data-login=setup][data-ready]')")
    fill_and_submit(page, "setup", name="Owner", email="owner@example.com", password=PASSWORD)
    assert page.wait_for(SIGNED_IN, timeout=20)
    assert page.js("document.querySelector('#app-version').textContent") == "develop-1a2b3c4"
    page.js("location.hash = '#/settings'")
    assert page.wait_for("!!document.querySelector('[data-about-version]')?.textContent")
    time.sleep(1)  # the update check has answered by now
    assert page.js("document.querySelector('[data-about-version]').textContent") == "Development build (develop-1a2b3c4)"
    assert page.js("!document.querySelector('dialog.whats-new')")
    assert not page.errors, page.errors
