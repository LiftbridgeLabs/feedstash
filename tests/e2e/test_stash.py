import base64

import httpx

from support.images import PNG

DIALOG = "document.querySelector('dialog[open]')"


def submit_dialog(page, fill_js: str = "") -> None:
    assert page.wait_for(f"!!{DIALOG}")
    page.js(f"(() => {{ const d = {DIALOG}; {fill_js}; d.querySelector('form').requestSubmit(); }})()")


def test_sidebar_lists_feeds_before_the_stash(reader):
    sections = reader.js("[...document.querySelectorAll('#nav .nav-section span')].map(e => e.textContent)")
    assert sections == ["Feeds", "Stash"]
    labels = reader.js("[...document.querySelectorAll('#nav > .nav-row .nav-label')].map(e => e.textContent)")
    assert labels == ["All articles", "Read later", "Inbox", "Everything saved", "Archive"]


def test_brand_goes_to_the_feeds(reader):
    reader.js("location.hash = '#/stash/inbox'")
    assert reader.wait_for("reader.state.route.scope === 'stash'")
    reader.js("document.querySelector('.brand').click()")
    assert reader.wait_for("reader.state.route.scope === 'all' && !document.querySelector('#articles').hidden")


def test_capture_review_filter_by_tag_and_archive(reader):
    reader.js("location.hash = '#/stash/inbox'")
    assert reader.wait_for("document.querySelector('[data-stash-end]')?.textContent.includes('Inbox zero')")

    reader.press("c")
    submit_dialog(reader, """
      d.querySelector('input[value=snippet]').click();
      d.querySelector('textarea[name=content]').value = 'Remember this line';
      d.querySelector('input[name=title]').value = 'An idea';
      d.querySelector('input[name=tags]').value = 'ideas'""")
    assert reader.wait_for("[...document.querySelectorAll('#stash .item-title')].some(e => e.textContent === 'An idea')")
    assert reader.wait_for("reader.state.stash.summary.inbox === 1")
    assert "1" in reader.js("document.querySelector('#nav [data-href=\"#/stash/inbox\"] .nav-count').textContent")

    reader.js("document.querySelector('#stash .item [data-stash-action=review]').click()")
    assert reader.wait_for("document.querySelectorAll('#stash .item').length === 0 && reader.state.stash.summary.inbox === 0")

    reader.js("location.hash = '#/stash/all'")
    assert reader.wait_for("document.querySelectorAll('#stash .item').length === 1")
    reader.js("document.querySelector('#stash .tag-chips [data-tag=ideas]').click()")
    assert reader.wait_for("location.hash === '#/stash/tag/ideas' && document.querySelectorAll('#stash .item').length === 1")

    reader.js("document.querySelector('#stash .item-row').click()")
    assert reader.wait_for("document.querySelector('#stash .item.open .stash-text')?.textContent === 'Remember this line'")
    reader.js("document.querySelector('#stash .item.open .reader-bar [data-stash-action=archive]').click()")
    assert reader.wait_for("reader.state.stash.summary.archived === 1 && document.querySelectorAll('#stash .item').length === 0")


def test_capture_a_note_with_several_links_and_reorder_them(reader):
    reader.js("location.hash = '#/stash/inbox'")
    assert reader.wait_for("document.querySelector('[data-stash-end]')?.textContent.includes('Inbox zero')")
    reader.press("c")
    submit_dialog(reader, """
      d.querySelector('input[name=title]').value = 'Research';
      d.querySelector('.link-url').value = 'example.com/first';
      d.querySelector('[data-link=add]').click();
      d.querySelectorAll('.link-url')[1].value = 'https://example.com/second';
      d.querySelectorAll('.link-label')[1].value = 'Second one'""")
    assert reader.wait_for("[...document.querySelectorAll('#stash .item-title')].some(e => e.textContent === 'Research')")
    assert "2 links" in reader.js("document.querySelector('#stash .item-meta').textContent")

    reader.js("document.querySelector('#stash .item-row').click()")
    assert reader.wait_for("document.querySelectorAll('#stash .item.open .stash-links li').length === 2")
    assert reader.js("document.querySelector('#stash .item.open .stash-links a').href") == "https://example.com/first"
    reader.js("document.querySelector('#stash .item.open .reader-bar [data-stash-action=edit]').click()")
    submit_dialog(reader, "d.querySelectorAll('.link-row')[1].querySelector('[data-link=up]').click()")
    assert reader.wait_for("document.querySelector('#stash .item.open .stash-links a')?.textContent === 'Second one'")
    item = reader.js("reader.api('GET', '/api/items').then((items) => items[0])")
    assert [link["url"] for link in item["links"]] == ["https://example.com/second", "https://example.com/first"]
    assert item["url"] == "https://example.com/second"


def test_paste_a_screenshot_into_the_capture_dialog(reader):
    reader.js("void reader.captureDialog()")  # don't wait: the promise resolves when the dialog closes
    assert reader.wait_for(f"!!{DIALOG}")
    reader.js("""(() => {
      const bytes = Uint8Array.from(atob('PNG_BASE64'), c => c.charCodeAt(0));
      const data = new DataTransfer();
      data.items.add(new File([bytes], 'clip.png', { type: 'image/png' }));
      const d = document.querySelector('dialog[open]');
      d.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
    })()""".replace("PNG_BASE64", base64.b64encode(PNG).decode()))
    assert reader.js(f"{DIALOG}.querySelector('input[value=screenshot]').checked")
    assert reader.wait_for(f"!{DIALOG}.querySelector('.capture-preview').hidden")
    submit_dialog(reader, "d.querySelector('input[name=title]').value = 'Pasted shot'")

    assert reader.wait_for("reader.state.stash.summary.by_type.screenshot === 1")
    reader.js("location.hash = '#/stash/all'")
    assert reader.wait_for("!!document.querySelector('#stash [data-type-filter=screenshot]')")
    reader.js("document.querySelector('#stash [data-type-filter=screenshot]').click()")
    assert reader.wait_for("location.hash === '#/stash/screenshot'")
    assert reader.js("document.querySelector('#nav [data-href=\"#/stash/all\"]').classList.contains('active')")
    assert reader.wait_for("document.querySelector('#stash .item .thumb')?.complete && document.querySelector('#stash .item .thumb').naturalWidth === 1")


def test_save_a_feed_article_to_the_stash(reader):
    reader.js("""[...document.querySelectorAll('#articles .item')]
      .find(e => e.textContent.includes('Tech story 0 ')).querySelector('.item-row').click()""")
    assert reader.wait_for("!!document.querySelector('#articles .item.open [data-action=stash]')")
    reader.js("document.querySelector('#articles .item.open [data-action=stash]').click()")
    assert reader.wait_for("reader.state.stash.summary.inbox === 1")

    reader.js("location.hash = '#/stash/inbox'")
    assert reader.wait_for("[...document.querySelectorAll('#stash .item-title')].some(e => e.textContent.startsWith('Tech story 0 '))")
    assert "via feed" in reader.js("document.querySelector('#stash .item-meta').textContent")


def test_create_use_and_revoke_an_api_token(reader, server):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("document.querySelector('[data-token-list]')?.textContent.includes('No tokens yet')")
    reader.js("document.querySelector('[data-settings=new-token]').click()")
    submit_dialog(reader, "d.querySelector('input[name=name]').value = 'Chrome extension'")

    assert reader.wait_for(f"!!document.querySelector('dialog[open] [data-token-value]')")
    token = reader.js("document.querySelector('dialog[open] [data-token-value]').value")
    headers = {"Authorization": f"Bearer {token}"}
    assert httpx.get(server.base_url + "/api/items", headers=headers).status_code == 200
    submit_dialog(reader)  # Done

    assert reader.wait_for("document.querySelector('[data-token-list]').textContent.includes('Chrome extension')")
    reader.js("document.querySelector('[data-settings=revoke]').click()")
    submit_dialog(reader)
    assert reader.wait_for("document.querySelector('[data-token-list]').textContent.includes('No tokens yet')")
    assert httpx.get(server.base_url + "/api/items", headers=headers).status_code == 401
