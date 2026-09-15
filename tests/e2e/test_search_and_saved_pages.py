def type_search(page, text: str) -> None:
    page.js(f"""(() => {{
      const box = document.getElementById('article-search');
      box.value = {text!r};
      box.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }})()""")


def test_search_articles_from_the_toolbar(reader):
    type_search(reader, "atom body 7")
    shown = "[...document.querySelectorAll('#articles .item-title')].map((e) => e.textContent.trim()).join('|')"
    assert reader.wait_for(f"{shown} === 'Atom post 7'")
    assert reader.js("document.querySelector('[data-dropdown=\"mark-menu\"]').disabled")

    type_search(reader, "")
    assert reader.wait_for("document.querySelectorAll('#articles .item').length >= 40")
    assert not reader.js("document.querySelector('[data-dropdown=\"mark-menu\"]').disabled")


def test_a_saved_link_shows_its_preview_and_saved_copy(browser_page, start_server, feed_server):
    server = start_server(PAGE_CAPTURE="true")
    page = browser_page
    page.goto(server.base_url + "/auth/login")
    assert page.wait_for("!!window.reader && reader.state.tree.page_capture === true", timeout=20)
    # With nothing followed the app opens on the (empty) Inbox, so go to another view once the link is saved.
    page.js(f"reader.api('POST', '/api/items', {{ type: 'link', url: '{feed_server}/article.html' }})"
            ".then(() => { location.hash = '#/stash/all'; })")
    assert page.wait_for("location.hash === '#/stash/all'")

    # The row starts as a bare address and picks up the page's title and image once it's saved.
    title = "document.querySelector('#stash .item-title')?.textContent"
    assert page.wait_for(f"{title} === 'The best reefs for beginner divers'", timeout=25)
    assert page.wait_for("!!document.querySelector('#stash .item .thumb')")

    page.js("document.querySelector('#stash .item-row').click()")
    assert page.wait_for("document.querySelector('#stash .saved-page-body')?.textContent.includes('Bonaire lets you')", timeout=10)
    assert not page.errors, page.errors
