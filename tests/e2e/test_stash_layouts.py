"""The stash as a list, a grid (cards keep their own height) or tiles, chosen per view."""

import time

from support.images import PNG

CARDS = "[...document.querySelectorAll('#stash .stash-item')]"


def seed(api) -> None:
    api.post("/api/items", data={"type": "screenshot", "title": "A picture", "content": "Notes about the picture"},
             files={"image": ("p.png", PNG, "image/png")}).raise_for_status()
    api.post("/api/stash/folders", json={"name": "Boards"}).raise_for_status()
    long_notes = "A long note that keeps going. " * 12
    for title in ("Short", "Long"):
        api.post("/api/items", json={"type": "snippet", "title": title, "content": long_notes if title == "Long" else "x",
                                     "folder": "Boards"}).raise_for_status()


def choose(page, layout: str) -> None:
    page.js(f"document.querySelector('[data-stash-layout-choice={layout}]').click()")
    assert page.wait_for(f"document.querySelector('#stash').dataset.stashLayout === '{layout}'")


def test_each_view_keeps_its_own_layout(reader, api):
    seed(api)
    reader.js("location.hash = '#/stash/all'")
    assert reader.wait_for(f"{CARDS}.length === 3")
    assert reader.js("document.querySelector('#stash').dataset.stashLayout") == "list"

    choose(reader, "grid")
    # Grid cards span as many rows as their content needs, so a long note makes a taller card.
    assert reader.wait_for(f"{CARDS}.every(c => c.style.gridRowEnd.startsWith('span'))")
    spans = reader.js(f"Object.fromEntries({CARDS}.map(c => [c.querySelector('.item-title').textContent, parseInt(c.style.gridRowEnd.split(' ')[1])]))")
    assert spans["Long"] > spans["Short"]
    assert reader.js(f"{CARDS}.some(c => c.querySelector('.item-summary')?.textContent.includes('Notes about the picture'))")

    # Opening a card spreads it across the row; closing puts it back.
    reader.js(f"{CARDS}.find(c => c.querySelector('.item-title').textContent === 'Short').querySelector('.item-row').click()")
    assert reader.wait_for("!!document.querySelector('#stash .stash-item.open .reader')")
    width = reader.js("document.querySelector('#stash .stash-item.open').getBoundingClientRect().width")
    assert width >= reader.js("document.querySelector('[data-stash-items]').getBoundingClientRect().width") - 60
    reader.js("document.querySelector('[data-stash-action=close]').click()")
    assert reader.wait_for("!document.querySelector('#stash .stash-item.open')")

    # Another view starts as a list; switching it to tiles leaves Everything saved as a grid.
    folder = api.get("/api/stash/summary").json()["folders"][0]["id"]
    reader.js(f"location.hash = '#/stash/folder/{folder}'")
    assert reader.wait_for(f"{CARDS}.length === 2 && document.querySelector('#stash').dataset.stashLayout === 'list'")
    choose(reader, "tiles")
    assert reader.js(f"{CARDS}.every(c => !c.style.gridRowEnd)")
    reader.js("location.hash = '#/stash/all'")
    assert reader.wait_for(f"{CARDS}.length === 3 && document.querySelector('#stash').dataset.stashLayout === 'grid'")

    # Kept across a reload; back to List clears the choice.
    reader.js("location.reload()")
    assert reader.wait_for(f"!!window.reader && {CARDS}.length === 3", timeout=20)
    assert reader.js("document.querySelector('#stash').dataset.stashLayout") == "grid"
    choose(reader, "list")
    assert reader.js(f"{CARDS}.every(c => !c.style.gridRowEnd)")
    time.sleep(0.2)
    assert reader.js("JSON.parse(localStorage.getItem('reader.stashLayouts'))['all']") is None
