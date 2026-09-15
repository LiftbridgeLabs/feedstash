import json

OPML = """<?xml version="1.0"?><opml version="2.0"><head><title>Feedly</title></head><body>
<outline text="Tech"><outline type="rss" text="Test Tech" xmlUrl="{feed_server}/tech.xml"/></outline>
</body></opml>"""
BOARD = """<!DOCTYPE NETSCAPE-Bookmark-file-1><H1>Feedly - Projects</H1><DL><p>
<DT><A HREF="https://example.com/kegbot" ADD_DATE="1392772835">Kegbot build guide</A></DL><p>"""
HISTORY = """<!DOCTYPE NETSCAPE-Bookmark-file-1><H1>Read in 2014-01</H1><DL><p>
<DT><A HREF="https://example.com/old" ADD_DATE="1390000000">Something read once</A></DL><p>"""


def test_choosing_a_whole_feedly_export_folder(reader, subscriptions):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!!document.querySelector('[data-import-folder]')")
    assert reader.js("document.querySelector('#app-version').textContent") == "dev"
    # Every import and export lives here, none on Organize feeds.
    assert reader.js("!!document.querySelector('[data-import-opml]') && !!document.querySelector('#settings a[href=\"/api/opml/export\"]')")
    assert reader.js("!document.querySelector('#organize [data-org=import]')")
    files = [
        [OPML.format(feed_server=subscriptions.feed_server), "subscriptions.opml"],
        [BOARD, "board-Projects-bookmarks.html"],
        [HISTORY, "read-2014-01-bookmarks.html"],  # would sit under read/ in a real export; treated as a board here
        ["{}", "profile.json"],
    ]
    reader.js("""(() => {
      const data = new DataTransfer();
      for (const [text, name] of FILES) data.items.add(new File([text], name, { type: 'text/plain' }));
      const input = document.querySelector('[data-import-folder]');
      input.files = data.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    })()""".replace("FILES", json.dumps(files)))

    # The OPML went through the feed import (Test Tech was already followed, so it reports as skipped)...
    assert reader.wait_for("document.querySelector('#toast')?.textContent.includes('already followed')", timeout=15)
    # ...and the boards became plan rows, the history file unticked by its heading.
    assert reader.wait_for("document.querySelectorAll('.import-plan tbody tr').length === 2", timeout=15)
    checks = reader.js("[...document.querySelectorAll('[data-import-field=include]')].map((el) => el.checked)")
    assert checks == [True, False]
    assert "Import 1 link" in reader.js("document.querySelector('[data-import-action=run]').textContent")
