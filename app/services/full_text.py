"""Full text for feed articles: fetches an article's own page and keeps its readable part with the article.

Feeds that only send a summary can ask for this for every new article (the PageWorker does those in the
background), and a reader can ask for any single article.
"""

import asyncio

import httpx

from app.clock import now
from app.db import Database
from app.db.models import FullTextJob
from app.db.repositories import articles as articles_repo
from app.pages.fetch import NotAWebPage, PageError, fetch_page


async def fetch(db: Database, client: httpx.AsyncClient, job: FullTextJob) -> tuple[str | None, str | None]:
    """Fetches and stores one article's full text. Returns (content, error); exactly one is set."""
    try:
        page = await fetch_page(client, job.url)
        content, error = page.html, None if page.html else "Couldn't find the article on its page"
    except (PageError, NotAWebPage) as exc:
        content, error = None, str(exc)
    await asyncio.to_thread(_store, db, job, content, error)
    return content, error


def _store(db: Database, job: FullTextJob, content: str | None, error: str | None) -> None:
    with db.transaction() as conn:
        if content:
            articles_repo.save_full_text(conn, job.article_id, content, now=now())
        else:
            articles_repo.save_full_text_failure(conn, job.article_id, error or "Couldn't fetch the page", now=now())
