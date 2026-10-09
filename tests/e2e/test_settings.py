def test_choose_how_long_read_articles_are_kept(reader):
    reader.js("location.hash = '#/settings'")
    select = "document.querySelector('[data-settings-field=read-retention]')"
    assert reader.wait_for(f"{select}?.value === '30'")
    reader.js(f"(() => {{ const s = {select}; s.value = '7'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
    assert reader.wait_for("reader.api('GET', '/api/me').then((me) => me.read_retention_days === 7)")

    reader.js("location.hash = '#/all'")
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for(f"{select}?.value === '7'")


def test_mark_as_read_while_scrolling_is_in_settings_too(reader):
    reader.js("location.hash = '#/settings'")
    select = "document.querySelector('[data-settings-field=mark-on-scroll]')"
    assert reader.wait_for(f"{select}?.value === 'off'")
    reader.js(f"(() => {{ const s = {select}; s.value = 'on'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
    assert reader.wait_for("reader.state.prefs.markOnScroll === true")
    assert reader.js("JSON.parse(localStorage.getItem('reader.prefs')).markOnScroll") is True

    reader.js("location.hash = '#/all'")
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for(f"{select}?.value === 'on'")


def test_sign_out_other_browsers_keeps_this_one(reader):
    reader.js("location.hash = '#/settings'")
    button = "document.querySelector('[data-settings=sign-out-others]')"
    assert reader.wait_for(f"!!{button}")
    reader.js(f"{button}.click()")
    assert reader.wait_for("document.body.textContent.includes('Signed out of every other browser')")
    assert reader.wait_for("reader.api('GET', '/api/me').then((me) => !!me.email)")


def test_connect_a_phone_shows_a_qr_code(reader):
    reader.js("location.hash = '#/settings'")
    button = "document.querySelector('[data-settings=connect-phone]')"
    assert reader.wait_for(f"!!{button}")
    reader.js(f"{button}.click()")
    assert reader.wait_for("!!document.querySelector('dialog[open] .qr-code svg')")
    assert reader.wait_for("document.querySelector('[data-token-list]').textContent.includes('Phone or iPad')")
