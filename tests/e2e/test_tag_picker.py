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
