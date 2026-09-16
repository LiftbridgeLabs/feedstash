def test_filing_a_saved_item_in_a_folder(reader):
    page = reader
    page.js("reader.api('POST', '/api/stash/folders', { name: 'Project X' }).then(() => reader.loadTree())")
    assert page.wait_for("[...document.querySelectorAll('#nav .nav-label')].some((e) => e.textContent === 'Project X')")

    page.js("reader.api('POST', '/api/items', { type: 'link', url: 'https://example.com/plan', title: 'The plan' })")
    page.js("location.hash = '#/stash/all'")
    assert page.wait_for("document.querySelector('#stash .item-title')?.textContent === 'The plan'", timeout=10)

    # The folder picker on the open item files it, and the sidebar count follows.
    page.js("document.querySelector('#stash .item-row').click()")
    assert page.wait_for("!!document.querySelector('#stash [data-item-folder]')")
    page.js("""(() => {
      const select = document.querySelector('#stash [data-item-folder]');
      select.value = [...select.options].find((o) => o.textContent === 'Project X').value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    })()""")
    assert page.wait_for("document.querySelector('#nav [data-stash-folder] .nav-count')?.textContent === '1'", timeout=10)

    page.js("document.querySelector('#nav [data-stash-folder]').click()")
    assert page.wait_for(
        "location.hash.startsWith('#/stash/folder/') && document.querySelectorAll('#stash .item').length === 1"
    )
    assert page.js("document.getElementById('view-title').textContent") == "Project X"


def test_searching_the_stash_from_the_toolbar(reader):
    page = reader
    page.js("reader.api('POST', '/api/items', { type: 'snippet', content: 'Nudibranch sightings' })")
    page.js("reader.api('POST', '/api/items', { type: 'snippet', content: 'Groceries' })")
    page.js("location.hash = '#/stash/all'")
    assert page.wait_for("document.querySelectorAll('#stash .item').length === 2", timeout=10)

    page.js("""(() => {
      const box = document.getElementById('toolbar-search');
      box.value = 'nudibranch';
      box.dispatchEvent(new Event('input', { bubbles: true }));
    })()""")
    assert page.wait_for("document.querySelectorAll('#stash .item').length === 1", timeout=10)
    assert page.js("document.getElementById('toolbar-search').placeholder") == "Search your stash"
    assert page.wait_for("!!document.querySelector('[data-stash-action=\"save-list\"]')")


def test_the_sidebar_plus_menus_and_row_spacing(reader):
    page = reader
    menu_labels = "[...document.querySelectorAll('#context-menu button')].map((b) => b.textContent).join('|')"

    page.js("document.querySelector('[data-action=\"feeds-menu\"]').click()")
    assert page.wait_for(f"{menu_labels} === 'Follow a feed…|New folder…'")
    page.js("document.querySelector('#context-menu button:last-child').click()")
    assert page.wait_for("!!document.querySelector('dialog[open]')")
    page.js("document.querySelector('dialog[open] [data-cancel]').click()")

    page.js("document.querySelector('[data-action=\"stash-menu\"]').click()")
    assert page.wait_for(f"{menu_labels} === 'Save something…|New stash folder…'")
    page.js("document.body.click()")

    # Organize feeds moved out of the sidebar; it's reached from Settings now.
    assert page.js("!document.querySelector('.sidebar-foot [href=\"#/organize\"]')")

    page.js("reader.setPref('density', 'compact')")
    assert page.wait_for("document.documentElement.dataset.density === 'compact'")
    assert page.js("JSON.parse(localStorage.getItem('reader.prefs')).density") == "compact"


def test_something_saved_elsewhere_shows_up_without_a_reload(reader):
    """What arrives by email or from a client while the stash is open, e.g. the sidebar count says 1 but the list
    shows nothing."""
    page = reader
    page.js("location.hash = '#/stash/all'")
    assert page.wait_for("!!document.querySelector('[data-stash-end]')", timeout=10)

    page.js("reader.api('POST', '/api/items', { type: 'snippet', content: 'Arrived while open', source: 'email' })")
    page.js("reader.pollForNew()")
    assert page.wait_for(
        "[...document.querySelectorAll('#stash .item-title')].some((e) => e.textContent === 'Arrived while open')",
        timeout=10,
    )
    # The sidebar count and the list agree.
    assert page.js("document.querySelectorAll('#stash .item').length") == page.js("reader.state.stash.summary.total")


def test_choosing_a_theme(reader):
    page = reader
    page.js("location.hash = '#/settings'")
    assert page.wait_for("!!document.getElementById('theme-mode')")
    page.js("""(() => {
      const select = document.getElementById('theme-mode');
      select.value = 'dark';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    })()""")
    assert page.wait_for("document.documentElement.dataset.mode === 'dark'")

    page.js("document.querySelector('[data-scheme=\"nord\"]').click()")
    assert page.wait_for("document.documentElement.dataset.scheme === 'nord'")
    assert page.js("JSON.parse(localStorage.getItem('reader.theme')).mode") == "dark"
