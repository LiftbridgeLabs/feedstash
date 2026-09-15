"""Saving feed articles to the stash: by hand ("Save to stash"), or automatically for feeds set to do so."""

import sqlite3

from app.db.models import Article, StashItem
from app.db.repositories import items as items_repo
from app.db.repositories import stash_rules

MAX_TITLE = 1000


def stash_article(conn: sqlite3.Connection, user_id: int, article: Article, *, now: int) -> tuple[StashItem, bool]:
    """Saves an article as a link (a snippet when it has no address) and runs the stash rules on it.
    Returns the item and whether it's new: an article whose link is already saved isn't saved twice."""
    if article.url and (existing := items_repo.find_link(conn, user_id, article.url)):
        return existing, False
    item = items_repo.create(
        conn, user_id,
        type="link" if article.url else "snippet",
        title=(article.title or "").strip()[:MAX_TITLE] or None,
        content=article.summary or (None if article.url else article.title),
        url=article.url,
        image_name=None,
        source="feed",
        tags=[],
        now=now,
        feed_id=article.feed_id,
    )
    if stash_rules.apply(conn, user_id, item.id, now=now):
        item = items_repo.get(conn, user_id, item.id)
    return item, True
