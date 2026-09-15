import json

BOARD = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Bookmarks</TITLE>
<H1>Feedly - Diving</H1>
<DL><p>
  <DT><H3>Saved in 2019</H3>
  <DL><p>
    <DT><A HREF="https://example.com/reef" ADD_DATE="1568000000">Best reefs</A>
    <DT><A HREF="https://example.com/gear" ADD_DATE="1568000100">Dive gear</A>
  </DL><p>
</DL><p>"""

UNSAVED = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<H1>Feedly - Unsaved</H1>
<DL><p><DT><A HREF="https://example.com/gone" ADD_DATE="1392772835">Removed long ago</A></DL><p>"""


def test_import_feedly_board_files_from_settings(reader):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!!document.querySelector('[data-import-files]')")
    reader.js("""(() => {
      const data = new DataTransfer();
      data.items.add(new File([__BOARD__], 'board-Diving-bookmarks.html', { type: 'text/html' }));
      data.items.add(new File([__UNSAVED__], 'board-Unsaved-bookmarks.html', { type: 'text/html' }));
      const input = document.querySelector('[data-import-files]');
      input.files = data.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    })()""".replace("__BOARD__", json.dumps(BOARD)).replace("__UNSAVED__", json.dumps(UNSAVED)))

    assert reader.wait_for("document.querySelectorAll('.import-plan tbody tr').length === 2")
    row = "document.querySelector('[data-import-field={field}][data-index=\"{index}\"]')"
    assert reader.js(row.format(field="include", index=0) + ".checked") is True
    assert reader.js(row.format(field="tag", index=0) + ".value") == "diving"
    assert reader.js(row.format(field="include", index=1) + ".checked") is False  # Unsaved starts unticked
    assert "Import 2 links" in reader.js("document.querySelector('[data-import-action=run]').textContent")

    reader.js(row.format(field="destination", index=0) + ".value = 'inbox'")
    reader.js(row.format(field="destination", index=0) + ".dispatchEvent(new Event('change', { bubbles: true }))")
    reader.js("document.querySelector('[data-import-action=run]').click()")
    assert reader.wait_for("reader.state.stash.summary.inbox === 2 && !document.querySelector('.import-plan')")
