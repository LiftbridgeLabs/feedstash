"""The keyboard shortcuts can be found: ? shows them, Settings links to them, and the list matches what the keys do."""

import re
from pathlib import Path

SHEET = "document.querySelector('dialog.shortcuts[open]')"


def test_question_mark_shows_the_shortcuts_and_closes_them_again(reader):
    reader.press("?")
    assert reader.wait_for(f"!!{SHEET}")
    text = reader.js(f"{SHEET}.textContent")
    for what in ("Save something to your stash", "Open the next / previous article", "Mark everything in the list read"):
        assert what in text
    reader.press("?")
    assert reader.wait_for(f"!{SHEET}")


def test_settings_has_a_way_to_the_shortcuts(reader):
    reader.js("location.hash = '#/settings'")
    assert reader.wait_for("!!document.querySelector('[data-settings=shortcuts]')")
    reader.js("document.querySelector('[data-settings=shortcuts]').click()")
    assert reader.wait_for(f"!!{SHEET}")
    reader.js(f"{SHEET}.querySelector('button').click()")
    assert reader.wait_for(f"!{SHEET}")


def test_the_list_covers_every_key_the_app_answers_to():
    static = Path(__file__).resolve().parents[2] / "app" / "static" / "js"
    handled = set(re.findall(r"(?:e\.key === |case )'([^']+)'", (static / "keyboard.js").read_text()))
    combos = re.findall(r"\[\[([^\]]*)\]", (static / "shortcuts.js").read_text())  # the [['j', 'k'], ...] key lists
    listed = {key for combo in combos for key in re.findall(r"'([^']+)'", combo)}
    listed |= {"Escape", "A"}  # shown as Esc and Shift + A
    assert handled <= listed, f"keys missing from the shortcuts sheet: {handled - listed}"
