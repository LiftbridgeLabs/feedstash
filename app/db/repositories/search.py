"""Full-text search (SQLite FTS5) over stash items and feed articles.

Each index row has the same rowid as the item or article it describes. Deleting an item or article removes its
row through a trigger; writing one (re)builds it here.
"""

import re
import sqlite3

from app.text import html_to_text

MAX_TERMS = 16
MAX_BODY = 200_000
_WORD = re.compile(r"[^\W_]+")  # letters and digits, as the unicode61 tokenizer splits them

# SQL conditions for a WHERE clause; each takes one MATCH parameter from match_query().
ITEM_MATCH = "i.id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)"
ARTICLE_MATCH = "a.id IN (SELECT rowid FROM articles_fts WHERE articles_fts MATCH ?)"


def match_query(text: str | None) -> str | None:
    """An FTS5 query finding every word typed (stemmed, so "reefs" finds "reef"), with the last word as a prefix so
    results show up while it's still being typed. None when there are no words, e.g. only punctuation."""
    words = _WORD.findall(text or "")[:MAX_TERMS]
    if not words:
        return None
    terms = [f'"{word}"' for word in words]
    if len(words[-1]) >= 3:
        terms[-1] += "*"
    return " ".join(terms)


def index_item(conn: sqlite3.Connection, item_id: int) -> None:
    """(Re)builds an item's search entry from its title, notes, links, tags and saved page."""
    conn.execute("DELETE FROM items_fts WHERE rowid = ?", (item_id,))
    row = conn.execute(
        """SELECT i.title, i.content, i.url, p.title AS page_title, p.description, p.text
           FROM items i LEFT JOIN item_pages p ON p.item_id = i.id WHERE i.id = ?""",
        (item_id,),
    ).fetchone()
    if row is None:
        return
    links = conn.execute("SELECT url, label FROM item_links WHERE item_id = ?", (item_id,)).fetchall()
    tags = conn.execute(
        "SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_id = ?", (item_id,)
    ).fetchall()
    title = " ".join(part for part in (row["title"], row["page_title"]) if part)
    body = "\n".join(
        part for part in (
            row["content"], row["url"], *(link["url"] for link in links), *(link["label"] for link in links),
            *(tag["name"] for tag in tags), row["description"], row["text"],
        ) if part
    )
    conn.execute("INSERT INTO items_fts (rowid, title, body) VALUES (?, ?, ?)", (item_id, title, body[:MAX_BODY]))


def index_article(conn: sqlite3.Connection, article_id: int, title: str, text: str) -> None:
    conn.execute(
        "INSERT INTO articles_fts (rowid, title, body) VALUES (?, ?, ?)", (article_id, title, (text or "")[:MAX_BODY])
    )


def backfill(conn: sqlite3.Connection) -> tuple[int, int]:
    """Indexes items and articles that aren't in the search index yet (e.g. saved before search existed).
    Returns (items, articles) indexed."""
    item_ids = [row[0] for row in conn.execute("SELECT id FROM items WHERE id NOT IN (SELECT rowid FROM items_fts)")]
    for item_id in item_ids:
        index_item(conn, item_id)
    article_ids = [
        row[0] for row in conn.execute("SELECT id FROM articles WHERE id NOT IN (SELECT rowid FROM articles_fts)")
    ]
    for article_id in article_ids:
        row = conn.execute("SELECT title, content, summary FROM articles WHERE id = ?", (article_id,)).fetchone()
        index_article(conn, article_id, row["title"], html_to_text(row["content"] or row["summary"]))
    return len(item_ids), len(article_ids)
