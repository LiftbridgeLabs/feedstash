from app.db.repositories import items, stash_folders, users


def save(conn, user_id, title, **fields):
    return items.create(conn, user_id, type="snippet", title=title, content="", url=None, source="web", tags=[],
                        now=1, **fields)


def titles(changes):
    return [item.title for item in changes.items]


def test_changes_list_each_item_once_in_the_order_it_last_changed(conn, user_id):
    a, b = save(conn, user_id, "A"), save(conn, user_id, "B")
    everything = items.changes(conn, user_id, since=0)
    assert titles(everything) == ["A", "B"] and everything.deleted == [] and not everything.more

    items.update(conn, user_id, a.id, now=2, tags=["later"])
    after_edit = items.changes(conn, user_id, since=everything.cursor)
    assert titles(after_edit) == ["A"] and after_edit.items[0].tags == ["later"]
    assert titles(items.changes(conn, user_id, since=0)) == ["B", "A"]

    items.delete(conn, user_id, b.id)
    after_delete = items.changes(conn, user_id, since=after_edit.cursor)
    assert after_delete.items == [] and after_delete.deleted == [b.id]
    nothing = items.changes(conn, user_id, since=after_delete.cursor)
    assert nothing.items == [] and nothing.deleted == [] and nothing.cursor == after_delete.cursor


def test_changes_catch_writes_that_bypass_the_item_row(conn, user_id):
    folder = stash_folders.create(conn, user_id, "Projects")
    item = save(conn, user_id, "Filed", folder_id=folder.id)
    cursor = items.changes(conn, user_id, since=0).cursor

    conn.execute("DELETE FROM stash_folders WHERE id = ?", (folder.id,))  # the item drops out of the folder
    unfiled = items.changes(conn, user_id, since=cursor)
    assert titles(unfiled) == ["Filed"] and unfiled.items[0].folder_id is None

    conn.execute("INSERT INTO item_pages (item_id, url, status) VALUES (?, 'https://x.example.com', 'ready')",
                 (item.id,))  # the page saver finished
    assert titles(items.changes(conn, user_id, since=unfiled.cursor)) == ["Filed"]


def test_changes_page_through_and_stay_within_the_account(conn, user_id):
    other = users.upsert(conn, sub="sub-bo", email="bo@example.com", name="Bo", picture=None)
    for n in range(5):
        save(conn, user_id, f"Mine {n}")
    theirs = save(conn, other, "Theirs")
    first = items.changes(conn, user_id, since=0, limit=3)
    assert titles(first) == ["Mine 0", "Mine 1", "Mine 2"] and first.more
    rest = items.changes(conn, user_id, since=first.cursor, limit=3)
    assert titles(rest) == ["Mine 3", "Mine 4"] and not rest.more

    items.delete(conn, other, theirs.id)
    assert items.changes(conn, user_id, since=rest.cursor).deleted == []


def test_a_cursor_from_another_copy_of_the_database_asks_for_a_reload(conn, user_id):
    save(conn, user_id, "A")
    changes = items.changes(conn, user_id, since=10_000)
    assert changes.reset and changes.items == [] and changes.cursor == 0


def test_a_restored_backup_is_noticed_even_after_other_accounts_moved_on(conn, user_id):
    other = users.upsert(conn, sub="sub-bo", email="bo@example.com", name="Bo", picture=None)
    save(conn, user_id, "Mine")
    restored_cursor = items.changes(conn, user_id, since=0).cursor + 5  # handed out before the restore
    for n in range(10):
        save(conn, other, f"Theirs {n}")  # the server's log moves past the old cursor
    assert items.changes(conn, user_id, since=restored_cursor).reset


def test_a_deleted_account_leaves_no_tombstones(conn, user_id):
    save(conn, user_id, "A")
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    assert conn.execute("SELECT COUNT(*) FROM stash_changes").fetchone()[0] == 0
