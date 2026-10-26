"""Starter feeds to follow, in themed packs (discover.json, shipped in the image). Nothing is fetched to show them:
the catalog is read from the file once, so Discover works offline and tells nobody what you look at."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

CATALOG = Path(__file__).with_name("discover.json")


@dataclass(frozen=True, slots=True)
class DiscoverFeed:
    title: str
    url: str
    site: str
    about: str
    cadence: str  # roughly how often it posts, e.g. "Daily"


@dataclass(frozen=True, slots=True)
class Pack:
    id: str
    name: str
    description: str
    feeds: tuple[DiscoverFeed, ...]


@cache
def packs() -> tuple[Pack, ...]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return tuple(
        Pack(id=pack["id"], name=pack["name"], description=pack["description"],
             feeds=tuple(DiscoverFeed(**feed) for feed in pack["feeds"]))
        for pack in data["packs"]
    )
