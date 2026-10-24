"""Seeing the tags you have while tagging: the row of your tags, the look-alike nudge, and rename or merge."""

DIALOG = "document.querySelector('dialog[open]')"


def seed(reader):
    for title, tags in (("One", ["vibe", "code"]), ("Two", ["vibe"]), ("Three", ["design"])):
        reader.js(f"reader.api('POST', '/api/items', {{type: 'snippet', title: '{title}', content: 'x', tags: {tags!r}}})")
    reader.js("location.hash = '#/stash/all'")
    assert reader.wait_for("document.querySelectorAll('#stash .item').length === 3")


def test_the_save_dialog_shows_your_tags_and_nudges_look_alikes(reader):
    seed(reader)
    reader.press("c")  # the page hasn't seen these tags yet: the dialog fetches the current list
    assert reader.wait_for(f"{DIALOG}?.querySelectorAll('.tag-picker-row [data-pick]').length === 3")
    row = reader.js(f"[...{DIALOG}.querySelectorAll('.tag-picker-row [data-pick]')].map(b => b.dataset.pick)")
    assert row[0] == "vibe"  # the most used first
    # Typing a look-alike: the row offers the existing tag, and the nudge swaps it in.
    reader.js(f"""(() => {{ const i = {DIALOG}.querySelector('input[name=tags]'); i.value = 'vibes, ';
      i.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()""")
    assert reader.wait_for(f"{DIALOG}.querySelector('.tag-nudge')?.textContent.includes('#vibe')")
    reader.js(f"{DIALOG}.querySelector('.tag-nudge [data-pick]').click()")
    assert reader.js(f"{DIALOG}.querySelector('input[name=tags]').value") == "vibe, "
    # Tapping a chip adds it.
    reader.js(f"{DIALOG}.querySelector('.tag-picker-row [data-pick=design]').click()")
    assert reader.js(f"{DIALOG}.querySelector('input[name=tags]').value") == "vibe, design, "


def test_rename_or_merge_a_tag_from_its_view(reader):
    seed(reader)
    reader.js("location.hash = '#/stash/tag/code'")
    assert reader.wait_for("!!document.querySelector('[data-stash-action=rename-tag]')")
    reader.js("document.querySelector('[data-stash-action=rename-tag]').click()")
    assert reader.wait_for(f"!!{DIALOG}?.querySelector('input[name=value]')")
    reader.js(f"{DIALOG}.querySelector('input[name=value]').value = 'vibe'")
    reader.js(f"{DIALOG}.querySelector('[type=submit]').click()")
    assert reader.wait_for("location.hash === '#/stash/tag/vibe'")
    assert reader.wait_for("document.body.textContent.includes('Merged #code into #vibe')")
    assert reader.wait_for("JSON.stringify(reader.state.stash.tags.map(t => [t.name, t.count])) === '[[\"vibe\",2],[\"design\",1]]'")


def test_settings_tags_merge_the_checked_ones_into_one(reader):
    for title, tags in (("One", ["vibe"]), ("Two", ["vibe"]), ("Three", ["vibes"]), ("Four", ["vibing"]), ("Five", ["design"])):
        reader.js(f"reader.api('POST', '/api/items', {{type: 'snippet', title: '{title}', content: 'x', tags: {tags!r}}})")
    reader.js("location.reload()")
    assert reader.wait_for("!!window.reader && reader.state.stash.tags.length === 4", timeout=20)
    reader.js("location.hash = '#/stash/all'")
    # The stash page's "Manage tags" goes to Settings → Tags.
    assert reader.wait_for("!!document.querySelector('[data-stash-action=manage-tags]')")
    reader.js("document.querySelector('[data-stash-action=manage-tags]').click()")
    assert reader.wait_for("location.hash === '#/settings/stash' && !document.querySelector('[data-group=stash]').hidden && !!document.querySelector('[data-tag-settings] [data-tag-name]')")

    # Look-alikes are offered to check in one click.
    reader.js("document.querySelector('[data-check-group]').click()")
    checked = "[...document.querySelectorAll('[data-tag-name]:checked')].map(c => c.dataset.tagName).sort().join()"
    assert reader.wait_for(f"{checked} === 'vibe,vibes,vibing'")
    assert reader.js("document.querySelector('[data-tag-action=merge]').disabled") is False
    reader.js("document.querySelector('[data-tag-action=merge]').click()")
    assert reader.wait_for("document.querySelector('dialog[open] input[name=into]')?.value === 'vibe'")  # the most used
    reader.js("document.querySelector('dialog[open] form').requestSubmit()")
    assert reader.wait_for("document.body.textContent.includes('Merged 3 tags into #vibe (4 items)')")
    rows = "[...document.querySelectorAll('[data-tag-name]')].map(c => c.dataset.tagName).join()"
    assert reader.wait_for(f"{rows} === 'vibe,design'")
    assert not reader.js("document.querySelector('[data-check-group]')")  # nothing left that looks alike


def test_settings_tags_delete_the_checked_ones(reader):
    for title, tags in (("One", ["recipes", "dinner"]), ("Two", ["recipes"])):
        reader.js(f"reader.api('POST', '/api/items', {{type: 'snippet', title: '{title}', content: 'x', tags: {tags!r}}})")
    reader.js("reader.api('POST', '/api/stash/lists', {name: 'Recipe list', tag: 'recipes'})")
    reader.js("location.reload()")
    assert reader.wait_for("!!window.reader && document.querySelector('#sidebar, nav, body').textContent.includes('Recipe list')", timeout=20)
    reader.js("location.hash = '#/settings/stash'")
    box = "document.querySelector('[data-tag-settings]')"
    assert reader.wait_for(f"!!{box}?.querySelector('[data-tag-name=recipes]')", timeout=20)
    assert reader.js("document.querySelector('[data-tag-action=delete]').disabled") is True
    reader.js("document.querySelector('[data-tag-name=recipes]').click()")
    assert reader.wait_for("document.querySelector('[data-tag-action=delete]').disabled === false")
    reader.js("document.querySelector('[data-tag-action=delete]').click()")
    assert reader.wait_for("document.querySelector('dialog[open]')?.textContent.includes('Delete #recipes?')")
    reader.js("document.querySelector('dialog[open] form').requestSubmit()")
    assert reader.wait_for("document.body.textContent.includes('Deleted #recipes from 2 items')")
    rows = "[...document.querySelectorAll('[data-tag-name]')].map(c => c.dataset.tagName).join()"
    assert reader.wait_for(f"{rows} === 'dinner'")
    # The smart list that only showed #recipes is gone from the sidebar too, without a reload.
    assert reader.wait_for("!document.body.textContent.includes('Recipe list')")
