TOTAL_UNREAD = "reader.state.tree.feeds.reduce((n, f) => n + f.unread, 0)"
SERVER_UNREAD = "fetch('/api/tree').then(r => r.json()).then(t => t.feeds.reduce((n, f) => n + f.unread, 0))"
EVERY_ITEM_ABOVE_VIEW_IS_READ = """(() => {
  const top = document.getElementById('content').getBoundingClientRect().top;
  return [...document.querySelectorAll('.item')].filter(e => e.getBoundingClientRect().bottom <= top + 1)
    .every(e => e.classList.contains('read'));
})()"""
EVERY_ITEM_IN_OR_BELOW_VIEW_IS_UNREAD = """(() => {
  const top = document.getElementById('content').getBoundingClientRect().top;
  return [...document.querySelectorAll('.item')].filter(e => e.getBoundingClientRect().top > top + 5)
    .every(e => !e.classList.contains('read'));
})()"""


def test_scrolling_leaves_articles_unread_by_default(reader):
    assert reader.js("reader.state.prefs.markOnScroll") is False
    reader.js("document.getElementById('content').scrollTop = 1500")
    reader.pump(1.5)
    assert reader.js("document.querySelectorAll('.item.read').length") == 0
    assert reader.js(SERVER_UNREAD) == 75


def test_scrolling_marks_articles_read_and_loads_more(reader):
    assert reader.js(TOTAL_UNREAD) == 75
    reader.js("reader.setPref('markOnScroll', true)")
    assert reader.js("document.getElementById('view-count').textContent") == "75 unread"

    reader.js("document.getElementById('content').scrollTop = 1500")
    reader.pump(0.4)
    marked = reader.js("document.querySelectorAll('.item.read').length")
    assert marked > 5
    reader.pump(1.5)
    assert reader.js(SERVER_UNREAD) == 75 - marked
    assert reader.js(EVERY_ITEM_ABOVE_VIEW_IS_READ)
    assert reader.js(EVERY_ITEM_IN_OR_BELOW_VIEW_IS_UNREAD)

    reader.js("document.getElementById('content').scrollTop = 1e7")
    assert reader.wait_for("document.querySelectorAll('.item').length === 75")
    reader.js("document.getElementById('content').scrollTop = 1e7")
    reader.pump(2)
    assert "reached the end" in reader.js("document.getElementById('list-end').textContent")
    assert reader.js("document.querySelectorAll('.item:not(.read)').length") == 0


def test_open_article_inline_then_keyboard_next_and_star(reader):
    reader.js("""[...document.querySelectorAll('.item')]
      .find(e => e.textContent.includes('Tech story 0 ')).querySelector('.item-row').click()""")
    assert reader.wait_for("document.querySelector('.item.open .reader-body p') !== null")
    body = reader.js("document.querySelector('.item.open .reader-body').innerHTML")
    assert "javascript:" not in body
    assert 'target="_blank"' in body

    reader.press("j")
    reader.pump(0.5)
    assert "Tech story 0 " not in reader.js("document.querySelector('.item.open .reader-title').textContent")
    reader.press("s")
    assert reader.wait_for("reader.state.tree.starred_count === 1")


def test_mark_older_than_one_day_from_the_menu(reader):
    reader.js("document.querySelector('[data-dropdown=\"mark-menu\"]').click()")
    reader.pump(0.3)
    reader.js("document.querySelector('[data-mark=\"24\"]').click()")
    assert reader.wait_for("""(() => { const t = document.getElementById('toast');
      return !t.hidden && t.textContent.includes('older than 1 day as read'); })()""")
    assert reader.wait_for(f"{TOTAL_UNREAD} < 75")


def test_titles_only_layout(reader):
    reader.js("reader.setPref('layout', 'titles')")
    assert reader.js("document.getElementById('articles').classList.contains('layout-titles')")


def test_rename_folder_through_its_menu_and_see_it_on_organize(reader, subscriptions):
    folder_id = subscriptions.blogs_folder["id"]
    reader.js(f"reader.openContextMenu('folder', {folder_id}, document.querySelector('[data-folder-drag=\"{folder_id}\"]'))")
    reader.js("[...document.querySelectorAll('#context-menu button')].find(b => b.textContent === 'Rename').click()")
    reader.pump(0.3)
    reader.js("document.querySelector('dialog input').value = 'Engineering'; document.querySelector('dialog form').requestSubmit()")
    assert reader.wait_for("[...document.querySelectorAll('#nav .nav-label')].some(e => e.textContent === 'Engineering')")

    reader.js("location.hash = '#/organize'")
    assert reader.wait_for("document.querySelectorAll('[data-feed-rows] tr').length === 2")


def test_phone_width_has_no_horizontal_scroll(reader):
    reader.viewport(400, 860, mobile=True)
    reader.pump(1)
    assert reader.js("document.documentElement.scrollWidth <= window.innerWidth")
    reader.js("document.getElementById('menu-toggle').click()")
    assert reader.js("document.body.classList.contains('nav-open')")
