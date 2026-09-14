import sqlite3
import time

TREE = "fetch('/api/tree').then(r => r.json())"

# Simulates an HTML5 drag from `src` to a point `frac` of the way down `dst`.
DRAG = """((srcSel, dstSel, frac, drop) => {
  const src = document.querySelector(srcSel), dst = document.querySelector(dstSel);
  if (!src || !dst) throw new Error('missing ' + (!src ? srcSel : dstSel));
  const dt = new DataTransfer();
  const r = dst.getBoundingClientRect();
  const at = { bubbles: true, cancelable: true, dataTransfer: dt, clientX: r.left + 20, clientY: r.top + r.height * frac };
  src.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
  dst.dispatchEvent(new DragEvent('dragover', at));
  if (drop) {
    dst.dispatchEvent(new DragEvent('drop', at));
    src.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
  }
})"""


def drag(page, src, dst, frac, drop=True):
    page.js(f"{DRAG}({src!r}, {dst!r}, {frac}, {'true' if drop else 'false'})")
    page.pump(0.6)


def put_both_feeds_in_new_folders(page, subscriptions):
    script = """(async () => {
      const one = await reader.api('POST', '/api/folders', { name: 'One' });
      const two = await reader.api('POST', '/api/folders', { name: 'Two' });
      await reader.api('POST', '/api/feeds/reorder', { folder_id: one.id, ids: [TECH, ATOM] });
      await reader.loadTree();
      reader.applyRoute();
      return [one.id, two.id];
    })()"""
    return page.js(script.replace("TECH", str(subscriptions.tech["id"])).replace("ATOM", str(subscriptions.atom["id"])))


def feeds_in(page, folder_id):
    return page.js(f"{TREE}.then(t => t.feeds.filter(f => f.folder_id === {folder_id}).map(f => f.id))")


def test_drag_folders_and_feeds_in_the_sidebar(reader, subscriptions):
    one, two = put_both_feeds_in_new_folders(reader, subscriptions)
    tech, atom = subscriptions.tech["id"], subscriptions.atom["id"]

    drag(reader, f'[data-folder-drag="{two}"]', f'.folder[data-folder-id="{one}"]', 0.1, drop=False)
    assert reader.js(f"document.querySelector('.folder[data-folder-id=\"{one}\"]').classList.contains('drop-before')")
    drag(reader, f'[data-folder-drag="{two}"]', f'.folder[data-folder-id="{one}"]', 0.1)
    local = reader.js("reader.state.tree.folders.map(f => f.id)")
    assert local.index(two) == local.index(one) - 1
    assert reader.js(f"{TREE}.then(t => t.folders.map(f => f.id))") == local
    assert reader.js("[...document.querySelectorAll('.folder[data-folder-id]')].map(e => +e.dataset.folderId)") == local
    assert reader.js("!document.querySelector('.drop-before, .drop-after, .drop-target')")

    drag(reader, f'[data-feed="{atom}"]', f'[data-feed="{tech}"]', 0.1)
    assert feeds_in(reader, one) == [atom, tech]
    assert reader.js(f"[...document.querySelectorAll('.folder[data-folder-id=\"{one}\"] [data-feed]')].map(e => +e.dataset.feed)") == [atom, tech]

    drag(reader, f'[data-feed="{tech}"]', f'[data-folder-drag="{two}"]', 0.5)
    assert feeds_in(reader, two) == [tech]

    drag(reader, f'[data-feed="{tech}"]', f'[data-feed="{atom}"]', 0.9)
    assert feeds_in(reader, one) == [atom, tech]


def test_move_with_the_menu_and_organize_arrows(reader, subscriptions):
    one, _two = put_both_feeds_in_new_folders(reader, subscriptions)
    tech, atom = subscriptions.tech["id"], subscriptions.atom["id"]

    reader.js(f"reader.openContextMenu('feed', {atom}, document.querySelector('[data-feed=\"{atom}\"]'))")
    labels = reader.js("[...document.querySelectorAll('#context-menu button')].map(b => b.textContent)")
    assert "Move up" in labels and "Move down" not in labels
    reader.js("[...document.querySelectorAll('#context-menu button')].find(b => b.textContent === 'Move up').click()")
    reader.pump(0.6)
    assert feeds_in(reader, one) == [atom, tech]

    reader.js("location.hash = '#/organize'")
    assert reader.wait_for("document.querySelector('[data-org=\"folder-down\"]') !== null")
    first = reader.js("reader.state.tree.folders[0].id")
    reader.js(f"document.querySelector('[data-org=\"folder-down\"][data-id=\"{first}\"]').click()")
    reader.pump(0.6)
    assert reader.js(f"{TREE}.then(t => t.folders.map(f => f.id))")[1] == first
    assert reader.js("document.querySelector('[data-org=\"folder-up\"]').disabled")


def test_new_articles_appear_when_idle_and_offer_a_button_while_reading(reader, server, subscriptions):
    def add_article(feed_id, title):
        now = int(time.time())
        with sqlite3.connect(server.db_path) as db:
            db.execute(
                "INSERT INTO articles (feed_id, guid, title, published_at, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (feed_id, f"{title}-{now}", title, now + 60, now),
            )

    has_title = "[...document.querySelectorAll('.item-title')].some(e => e.textContent === {!r})"

    add_article(subscriptions.tech["id"], "Arrived while idle")
    reader.js("reader.pollForNew()")
    assert reader.wait_for(has_title.format("Arrived while idle"))
    assert reader.js("document.getElementById('new-banner').hidden")

    reader.js("reader.state.prefs.markOnScroll = false; document.getElementById('content').scrollTop = 900")
    reader.pump(0.4)
    add_article(subscriptions.atom["id"], "Arrived while reading")
    reader.js("reader.pollForNew()")
    assert reader.wait_for("!document.getElementById('new-banner').hidden")
    assert reader.js("document.getElementById('new-banner').textContent") == "↑ 1 new article"
    assert reader.js("document.getElementById('content').scrollTop") > 500
    size = reader.js("(() => { const b = document.getElementById('new-banner'); return [b.offsetHeight, b.scrollHeight <= b.clientHeight + 1]; })()")
    assert size[0] >= 28 and size[1], size

    reader.js("document.getElementById('new-banner').click()")
    assert reader.wait_for(has_title.format("Arrived while reading"))
    assert reader.js("document.getElementById('new-banner').hidden")
