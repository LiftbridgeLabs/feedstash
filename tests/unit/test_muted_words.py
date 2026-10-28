import pytest

from app.db.models import MutedWord
from app.db.repositories import feeds, folders, muted_words, users
from app.errors import InvalidInput, NotFound
from app.feeds import ingest
from app.feeds.mute import Matcher, clean
from app.feeds.parser import ParsedEntry, ParsedFeed
from app.services import muting

NOW = 1_800_000_000


def word(phrase: str, *, title_only: bool = True, folder_id: int | None = None, feed_id: int | None = None) -> MutedWord:
    return MutedWord(id=1, phrase=phrase, title_only=title_only, folder_id=folder_id, feed_id=feed_id)


def entry(guid: str, title: str, text: str = "") -> ParsedEntry:
    return ParsedEntry(guid=guid, title=title, url=None, author=None, summary="", content=text, image=None,
                       published_at=NOW)


def store(conn, feed_id: int, *entries: ParsedEntry, first_fetch: bool = False) -> int:
    feed = ParsedFeed(title="Feed", site_url=None, entries=list(entries))
    return ingest.save_entries(conn, feed_id, feed, first_fetch=first_fetch, retention_days=90, now=NOW)


def unread(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT guid FROM articles WHERE read_at IS NULL ORDER BY guid")]


# ------------------------------------------------------------------ matching


@pytest.mark.parametrize(("phrase", "title", "muted"), [
    ("AI", "AI's new model", True),
    ("AI", "The company said so", False),
    ("ai", "Ai and you", True),
    ("apple watch", "The Apple  Watch is back", True),
    ("apple watch", "Apple Watches compared", False),
    ("apple", "Pineapple season", False),
    ("C++", "What's new in C++ 26", True),
    ("#sponsored", "A deal #sponsored", True),
    ("Café", "CAFÉ opening", True),
])
def test_words_match_whole_words_ignoring_case(phrase, title, muted):
    assert Matcher.of([word(phrase)]).mutes(title, "") is muted


def test_title_only_words_ignore_the_text_and_others_read_both():
    text = "Buried in the third paragraph: crypto."
    assert not Matcher.of([word("crypto")]).mutes("Weekly news", text)
    assert Matcher.of([word("crypto", title_only=False)]).mutes("Weekly news", text)
    assert Matcher.of([word("crypto", title_only=False)]).mutes("Crypto news", "")


def test_a_word_applies_everywhere_or_only_in_its_folder_or_feed():
    words = [word("everywhere"), word("folder", folder_id=7), word("feed", feed_id=3)]
    in_folder = Matcher.for_feed(words, feed_id=3, folder_id=7)
    elsewhere = Matcher.for_feed(words, feed_id=4, folder_id=None)
    assert all(in_folder.mutes(title, "") for title in ("everywhere", "folder", "feed"))
    assert elsewhere.mutes("everywhere", "")
    assert not elsewhere.mutes("folder", "") and not elsewhere.mutes("feed", "")
    assert not Matcher.for_feed([], feed_id=1, folder_id=None)


def test_phrases_are_trimmed_and_spaces_collapsed():
    assert clean("  apple \n watch ") == "apple watch"


# ------------------------------------------------------------------ storing


def test_muting_the_same_phrase_in_the_same_place_keeps_one(conn, user_id):
    first = muted_words.create(conn, user_id, phrase="Crypto", now=NOW)
    again = muted_words.create(conn, user_id, phrase="crypto", title_only=False, now=NOW)
    assert again.id == first.id and not again.title_only
    folder = folders.create(conn, user_id, "Tech")
    assert muted_words.create(conn, user_id, phrase="crypto", folder_id=folder.id, now=NOW).id != first.id
    assert len(muted_words.list_for_user(conn, user_id)) == 2


def test_words_need_text_and_one_place_you_own(conn, user_id):
    other = users.upsert(conn, sub="sub-bo", email="bo@example.com", name="Bo", picture=None)
    their_feed = feeds.create(conn, other, url="https://b.example.com/feed", title="B")
    their_folder = folders.create(conn, other, "Theirs")
    mine = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    my_folder = folders.create(conn, user_id, "Mine")
    with pytest.raises(InvalidInput):
        muted_words.create(conn, user_id, phrase="", now=NOW)
    with pytest.raises(InvalidInput):
        muted_words.create(conn, user_id, phrase="x", folder_id=my_folder.id, feed_id=mine, now=NOW)
    with pytest.raises(NotFound):
        muted_words.create(conn, user_id, phrase="x", feed_id=their_feed, now=NOW)
    with pytest.raises(NotFound):
        muted_words.create(conn, user_id, phrase="x", folder_id=their_folder.id, now=NOW)
    theirs = muted_words.create(conn, other, phrase="x", now=NOW)
    with pytest.raises(NotFound):
        muted_words.delete(conn, user_id, theirs.id)


def test_a_folder_or_feed_takes_its_muted_words_with_it(conn, user_id):
    folder = folders.create(conn, user_id, "Tech")
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    muted_words.create(conn, user_id, phrase="in folder", folder_id=folder.id, now=NOW)
    muted_words.create(conn, user_id, phrase="in feed", feed_id=feed_id, now=NOW)
    conn.execute("DELETE FROM folders WHERE id = ?", (folder.id,))
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    assert muted_words.list_for_user(conn, user_id) == []


# ------------------------------------------------------------------ new articles


def test_new_articles_holding_a_muted_word_arrive_read(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    muted_words.create(conn, user_id, phrase="crypto", now=NOW)
    added = store(conn, feed_id, entry("1", "Crypto crash"), entry("2", "Garden news"), entry("3", "Weekly", "crypto"))
    assert added == 2  # the muted one isn't counted as new
    assert unread(conn) == ["2", "3"]
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 3
    assert conn.execute("SELECT last_new_at FROM feeds WHERE id = ?", (feed_id,)).fetchone()[0] == NOW


def test_muted_words_only_reach_their_own_folder_feed_and_account(conn, user_id):
    other = users.upsert(conn, sub="sub-bo", email="bo@example.com", name="Bo", picture=None)
    folder = folders.create(conn, user_id, "Tech")
    in_folder = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A", folder_id=folder.id)
    loose = feeds.create(conn, user_id, url="https://b.example.com/feed", title="B")
    theirs = feeds.create(conn, other, url="https://a.example.com/feed", title="A")
    muted_words.create(conn, user_id, phrase="rumor", folder_id=folder.id, now=NOW)
    store(conn, in_folder, entry("folder", "A rumor"))
    store(conn, loose, entry("loose", "A rumor"))
    store(conn, theirs, entry("theirs", "A rumor"))
    assert unread(conn) == ["loose", "theirs"]


def test_muted_articles_skip_the_auto_save(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    feeds.set_auto_stash(conn, user_id, feed_id, True)
    muted_words.create(conn, user_id, phrase="ad", now=NOW)
    store(conn, feed_id, entry("1", "An ad"), entry("2", "A story"))
    assert [row[0] for row in conn.execute("SELECT title FROM items")] == ["A story"]


def test_catching_up_marks_matching_unread_read_with_an_undoable_batch(conn, user_id):
    feed_id = feeds.create(conn, user_id, url="https://a.example.com/feed", title="A")
    store(conn, feed_id, entry("1", "Crypto crash"), entry("2", "Garden news"), entry("3", "Weekly", "<p>crypto</p>"))
    title_word = muted_words.create(conn, user_id, phrase="crypto", now=NOW)
    assert muting.mark_unread_read(conn, user_id, title_word, batch=NOW + 5) == 1
    text_word = muted_words.create(conn, user_id, phrase="crypto", title_only=False, now=NOW)
    assert muting.mark_unread_read(conn, user_id, text_word, batch=NOW + 6) == 1
    assert unread(conn) == ["2"]
    assert conn.execute("SELECT read_at FROM articles WHERE guid = '3'").fetchone()[0] == NOW + 6
