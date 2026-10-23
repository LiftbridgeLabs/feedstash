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


def test_a_token_can_be_renamed_from_its_row(reader):
    reader.js("reader.api('POST', '/api/tokens', { clientName: 'Phone or iPad' })")
    reader.js("location.hash = '#/settings'")
    button = "document.querySelector('[data-settings=rename-token]')"
    assert reader.wait_for(f"!!{button}")
    reader.js(f"{button}.click()")
    assert reader.wait_for("document.querySelector('dialog[open] [name=value]')?.value === 'Phone or iPad'")
    reader.js("""(() => { const d = document.querySelector('dialog[open]');
      d.querySelector('[name=value]').value = 'iPad mini'; d.querySelector('[type=submit]').click(); })()""")
    assert reader.wait_for("document.querySelector('[data-token-list]').textContent.includes('iPad mini')")
    assert reader.wait_for("reader.api('GET', '/api/tokens').then((t) => t[0].clientName === 'iPad mini')")


def test_admins_see_about_with_where_to_get_help(reader):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!document.querySelector('[data-about-section]')?.hidden")
    about = reader.js("document.querySelector('[data-about-section]').textContent")
    assert "Development build" in about and "Suggest a feature" in about
    links = reader.js("[...document.querySelectorAll('[data-about-section] a')].map(a => a.getAttribute('href'))")
    assert any(link.endswith("/issues/new") for link in links)
    assert any(link.startswith("mailto:support@") for link in links)


def test_someone_can_hide_the_feeds_or_the_stash(reader):
    sections = "[...document.querySelectorAll('#nav .nav-section span')].map(e => e.textContent).join(',')"
    assert reader.js(sections) == "Feeds,Stash"
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!!document.querySelector('[data-settings-field=sections]')")

    def use(value):
        reader.js(f"(() => {{ const s = document.querySelector('[data-settings-field=sections]'); s.value = '{value}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")

    use("stash")
    assert reader.wait_for(f"{sections} === 'Stash'")
    assert reader.js("document.querySelector('#add-menu [data-add=follow]').hidden")
    # Feeds-only parts of Settings hide; the Stash group stays, and the Feeds group is just Import.
    assert reader.js("[...document.querySelectorAll('[data-only=feeds]')].every((el) => el.hidden)")
    assert reader.js("!document.querySelector('[data-group-link=stash]').hidden")
    assert reader.js("document.querySelector('[data-group-link=feeds]').textContent") == "Import"
    reader.js("location.hash = '#/all'")  # an old link into the feeds
    assert reader.wait_for("location.hash === '#/stash/all'")

    use_from_anywhere = "reader.api('PATCH', '/api/account', { sections: 'feeds' })"
    reader.js(use_from_anywhere)
    reader.js("location.reload()")
    assert reader.wait_for(f"!!window.reader && {sections} === 'Feeds'", timeout=20)
    assert reader.wait_for("location.hash === '#/all'")  # the stash link it was on redirects too
    assert reader.js("document.querySelector('#capture-btn').hidden")
    reader.press("c")
    assert not reader.js("!!document.querySelector('dialog[open]')")

    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!!document.querySelector('[data-settings-field=sections]')")
    use("both")
    assert reader.wait_for(f"{sections} === 'Feeds,Stash'")


def test_admins_set_and_read_the_logs_in_settings(reader):
    reader.js("reader.api('POST', '/api/items', { type: 'snippet', content: 'something to log' })")
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!document.querySelector('[data-logs-section]')?.hidden && !!document.querySelector('[data-log-field=requests]')")
    assert reader.wait_for("document.querySelector('[data-log-view]').textContent.includes('POST /api/items')")
    reader.js("(() => { const s = document.querySelector('[data-log-field=max_mb]'); s.value = '25'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    assert reader.wait_for("reader.api('GET', '/api/admin/logs/settings').then((s) => s.max_mb === 25)")
    assert reader.js("document.querySelector('[data-logs-section] a[download]').getAttribute('href')") == "/api/admin/logs/download"


def test_admins_add_a_single_sign_on_in_settings(reader, oidc_provider):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!document.querySelector('[data-signin-section]')?.hidden && !!document.querySelector('[data-signin-allowed-form]')")
    assert "Only passwords so far" in reader.js("document.querySelector('[data-signin-list]').textContent")

    reader.js("document.querySelector('[data-signin=add]').click()")
    assert reader.wait_for("!!document.querySelector('dialog.modal [name=issuer]')")
    # The redirect URI to give the provider shows before anything is saved.
    assert "/auth/sso/callback" in reader.js("document.querySelector('dialog.modal [data-callbacks]').textContent")
    reader.js(f"""(() => {{
      const d = document.querySelector('dialog.modal');
      d.querySelector('[name=name]').value = 'Pocket ID';
      d.querySelector('[name=issuer]').value = '{oidc_provider.issuer}';
      d.querySelector('[name=client_id]').value = 'feedstash-test';
      d.querySelector('[name=client_secret]').value = 'test-client-secret';
      const icon = d.querySelector('[name=icon_choice]'); icon.value = 'shield'; icon.dispatchEvent(new Event('change', {{ bubbles: true }}));
      const use = d.querySelector('[name=use_color]'); use.checked = true; use.dispatchEvent(new Event('change', {{ bubbles: true }}));
      const color = d.querySelector('[name=color]'); color.value = '#1e3a8a'; color.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }})()""")
    # The preview shows the button as it will look.
    preview = reader.js("document.querySelector('dialog.modal [data-preview]').innerHTML")
    assert "Sign in with Pocket ID" in preview and "shield.svg" in preview and "#1e3a8a" in preview
    reader.js("document.querySelector('dialog.modal [type=submit]').click()")
    assert reader.wait_for("!document.querySelector('dialog.modal')")
    assert reader.wait_for("document.querySelector('[data-signin-list]').textContent.includes('Pocket ID')")
    assert "shield.svg" in reader.js("document.querySelector('.sso-row-button').innerHTML")

    # One switch hides every button, and shows them again.
    reader.js("(() => { const s = document.querySelector('[data-signin-switch-field]'); s.value = 'off'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    assert reader.wait_for("reader.api('GET', '/api/admin/sign-in').then((s) => s.sso_enabled === false)")
    assert reader.wait_for("document.querySelector('.sso-row').classList.contains('is-off')")
    reader.js("(() => { const s = document.querySelector('[data-signin-switch-field]'); s.value = 'on'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    assert reader.wait_for("reader.api('GET', '/api/admin/sign-in').then((s) => s.sso_enabled === true)")

    # "Anyone it signs in" is a choice per sign-in, saved with it.
    reader.js("document.querySelector('[data-signin=edit]').click()")
    assert reader.wait_for("!!document.querySelector('dialog.modal [name=trust_all]')")
    reader.js("(() => { const s = document.querySelector('dialog.modal [name=trust_all]'); s.value = 'anyone'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    assert "Everyone Pocket ID allows" in reader.js("document.querySelector('dialog.modal [data-everyone]').textContent")
    assert "Pocket ID decides who gets in" in reader.js("document.querySelector('dialog.modal [data-access-hint]').textContent")
    reader.js("document.querySelector('dialog.modal [type=submit]').click()")
    assert reader.wait_for("reader.api('GET', '/api/admin/sign-in').then((s) => s.providers[0].trust_all === true)")
    assert reader.wait_for("document.querySelector('[data-signin-list]').textContent.includes('everyone pocket id allows')")

    # Choosing Google hides the issuer and name, and says where Google's setting is.
    reader.js("document.querySelector('[data-signin=add]').click()")
    assert reader.wait_for("!!document.querySelector('dialog.modal [name=kind]')")
    reader.js("(() => { const s = document.querySelector('dialog.modal [name=kind]'); s.value = 'google'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    assert reader.js("document.querySelector('dialog.modal [name=issuer]').closest('[data-oidc-only]').hidden") is True
    assert "Google Cloud Console" in reader.js("document.querySelector('dialog.modal [data-where]').textContent")
    # And has no "everyone" choice at all: anyone can have a Google account.
    assert reader.js("document.querySelector('dialog.modal [data-access]').hidden") is True
    assert "anyone can have a Google account" in reader.js("document.querySelector('dialog.modal [data-google-access]').textContent")
    reader.js("document.querySelector('dialog.modal [data-cancel]').click()")

    reader.js("""(() => {
      const f = document.querySelector('[data-signin-allowed-form]');
      f.querySelector('[name=emails]').value = 'ann@example.com, bo@example.com';
      f.querySelector('[type=submit]').click();
    })()""")
    assert reader.wait_for("reader.api('GET', '/api/admin/sign-in').then((s) => s.allowed_emails.length === 2)")


def test_settings_shows_one_group_at_a_time_with_its_own_address(reader):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!!document.querySelector('[data-settings-nav] a.active')")
    shown = "[...document.querySelectorAll('[data-group]')].filter((g) => !g.hidden).map((g) => g.dataset.group).join(',')"
    assert reader.js(shown) == "you"
    reader.js("document.querySelector('[data-group-link=apps]').click()")
    assert reader.wait_for("location.hash === '#/settings/apps'")
    assert reader.wait_for(f"{shown} === 'apps'")
    assert reader.js("document.querySelector('[data-group-link=apps]').getAttribute('aria-current')") == "page"
    # Switching groups keeps the page: something typed in another group is still there.
    assert reader.wait_for("!!document.querySelector('[data-signin-allowed-form] [name=emails]')")
    reader.js("document.querySelector('[data-signin-allowed-form] [name=emails]').value = 'typed@example.com'")
    reader.js("location.hash = '#/settings/admin'")
    assert reader.wait_for(f"{shown} === 'admin'")
    assert reader.js("document.querySelector('[data-signin-allowed-form] [name=emails]').value") == "typed@example.com"
    # An unknown group opens You.
    reader.js("location.hash = '#/settings/nope'")
    assert reader.wait_for(f"{shown} === 'you'")


def test_opening_the_admin_group_directly_lands_on_it(reader):
    reader.js("location.hash = '#/settings/admin'; location.reload()")
    reader.pump(2)
    assert reader.wait_for("!!window.reader && !document.querySelector('[data-group=admin]')?.hidden", timeout=20)
    assert reader.js("document.querySelector('[data-group-link=admin]').classList.contains('active')")


def test_apps_says_when_the_address_is_local_and_when_the_worker_isnt_bundled(reader):
    reader.js("location.hash = '#/settings/apps'")
    assert reader.wait_for("!document.querySelector('[data-group=apps]').hidden")
    # Tests run from source on 127.0.0.1: the worker isn't bundled, and the address isn't one Cloudflare can reach.
    assert reader.wait_for("document.querySelector('[data-worker-download]').textContent.includes('runs from source')")
    cloudflare = "[...document.querySelectorAll('.settings-card')].find((c) => c.querySelector('h3')?.textContent === 'Email with Cloudflare').textContent.replace(/\\s+/g, ' ')"
    assert "Cloudflare can't reach" in reader.js(cloudflare)
    assert reader.js("!!document.querySelector('a[href=\"/downloads/feedstash-extension.zip\"]')")
    assert reader.js("!!document.querySelector('a[href^=\"https://chromewebstore.google.com/detail/feedstash-capture/\"]')")
