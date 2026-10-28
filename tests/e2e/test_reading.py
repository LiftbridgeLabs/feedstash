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


def test_a_folders_own_menu_marks_older_articles_read(reader, subscriptions):
    folder_id = subscriptions.blogs_folder["id"]
    before = reader.js(f"reader.state.tree.feeds.filter(f => f.folder_id === {folder_id}).reduce((n, f) => n + f.unread, 0)")
    reader.js(f"reader.openContextMenu('folder', {folder_id}, document.querySelector('[data-folder-drag=\"{folder_id}\"]'))")
    labels = reader.js("[...document.querySelectorAll('#context-menu button')].map(b => b.textContent)")
    assert labels[:4] == ["Mark all as read", "Mark read: older than 12 hours", "Mark read: older than 1 day",
                          "Mark read: older than 1 week"]
    reader.js("[...document.querySelectorAll('#context-menu button')].find(b => b.textContent.endsWith('1 day')).click()")
    assert reader.wait_for("""(() => { const t = document.getElementById('toast');
      return !t.hidden && t.textContent.includes('older than 1 day as read'); })()""")
    after = f"reader.state.tree.feeds.filter(f => f.folder_id === {folder_id}).reduce((n, f) => n + f.unread, 0)"
    assert reader.wait_for(f"{after} < {before} && {after} > 0")  # older ones read, the newest left


def test_titles_only_layout(reader):
    reader.js("reader.setPref('layout', 'titles')")
    assert reader.js("document.getElementById('articles').classList.contains('layout-titles')")


PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def test_cards_layout_puts_articles_side_by_side_and_an_open_one_across(reader):
    reader.js("reader.setPref('layout', 'cards')")
    articles = "document.getElementById('articles')"
    assert reader.js(f"{articles}.classList.contains('layout-cards') && getComputedStyle({articles}).display") == "grid"
    first, second = "document.querySelectorAll('.item')[0]", "document.querySelectorAll('.item')[1]"
    assert reader.js(f"{first}.getBoundingClientRect().top === {second}.getBoundingClientRect().top")  # one row
    # The test feeds' pictures are on example.com and get removed when they fail to load, so the card gets one that
    # always loads; only its layout is under test.
    reader.js(f"""(() => {{ const row = {first}.querySelector('.item-row'); row.querySelector('.thumb')?.remove();
      row.append(Object.assign(document.createElement('img'), {{ className: 'thumb', src: '{PIXEL}' }})); }})()""")
    assert reader.wait_for(f"{first}.querySelector('.thumb')?.complete")
    picture = reader.js(f"(() => {{ const t = {first}.querySelector('.thumb').getBoundingClientRect(); "
                        f"const title = {first}.querySelector('.item-title').getBoundingClientRect(); "
                        "return t.width > t.height && t.width > 200 && t.bottom <= title.top; })()")
    assert picture  # a big picture above the title, not a thumbnail beside it
    reader.js(f"{first}.querySelector('.item-row').click()")
    assert reader.wait_for("!!document.querySelector('.item.open .reader-body p')")
    widths = reader.js(f"[document.querySelector('.item.open').getBoundingClientRect().width, {second}.getBoundingClientRect().width, "
                       f"{articles}.getBoundingClientRect().width]")
    assert widths[0] > widths[1] * 1.5 and widths[0] >= widths[2] - 48, widths  # the row less its padding, not a card


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


def test_cards_fit_a_narrow_phone_even_with_comfortable_spacing(reader):
    reader.js("reader.setPref('layout', 'cards'); reader.setPref('density', 'comfortable')")
    reader.viewport(340, 800, mobile=True)
    reader.pump(1)
    assert reader.js("document.documentElement.scrollWidth <= window.innerWidth")
    assert reader.js("document.querySelector('.item').getBoundingClientRect().right <= window.innerWidth")


def test_the_second_sanitizer_keeps_only_the_gallery_and_video_classes(reader):
    reader.js("""import('/static/js/sanitize.js').then(({ sanitize }) => {
      const box = document.createElement('div');
      box.append(sanitize('<div class="fs-gallery" onclick="steal()"><img src="https://x.example.com/1.jpg"></div>'
        + '<p class="fs-video"><a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Watch</a></p><p class="evil">x</p>'
        + '<img src="https://x.example.com/2.jpg"ONERROR="steal()"><p title="turn on" onmouseover=steal()>y</p>'
        + '<a href=/online>Online</a><img src=https://x.example.com/onion.jpg onload=steal()>'));
      window.sanitized = box.innerHTML;
    })""")
    assert reader.wait_for("typeof window.sanitized === 'string'")
    html = reader.js("window.sanitized")
    assert 'class="fs-gallery"' in html and 'class="fs-video"' in html
    assert "evil" not in html and "onclick" not in html and "steal" not in html
    # Only handler names are renamed, never anything inside a value, quoted or not.
    assert 'title="turn on"' in html and 'href="/online"' in html and 'src="https://x.example.com/onion.jpg"' in html


def test_a_feed_set_to_open_on_the_website_opens_a_tab_instead(reader, subscriptions):
    tech = subscriptions.tech["id"]
    reader.js(f"reader.openContextMenu('feed', {tech}, document.querySelector('[data-menu=\"feed\"][data-id=\"{tech}\"]'))")
    reader.js("[...document.querySelectorAll('#context-menu button')].find(b => b.textContent === 'Open articles as…').click()")
    assert reader.wait_for("!!document.querySelector('dialog[open] input[value=website]')")
    reader.js("""(() => {
      const dialog = document.querySelector('dialog[open]');
      dialog.querySelector('input[value=website]').checked = true;
      dialog.querySelector('[type=submit]').click();
    })()""")
    assert reader.wait_for(f"reader.state.tree.feeds.find(f => f.id === {tech}).open_website === true")

    reader.js("window.opened = []; window.open = (url) => { window.opened.push(url); return null; }")
    story = "[...document.querySelectorAll('.item')].find(e => e.textContent.includes('Tech story 0 '))"
    reader.js(f"{story}.querySelector('.item-row').click()")
    assert reader.wait_for("window.opened.length === 1 && window.opened[0] === 'https://example.com/tech/0'")
    assert reader.wait_for(f"{story}.classList.contains('read') && !document.querySelector('.item.open')")

    reader.press("j")  # moves on without opening another tab
    reader.pump(0.5)
    assert reader.js("window.opened.length") == 1
