"""Release notes from CHANGELOG.md, and asking GitHub whether a newer release is out."""

import asyncio

import httpx
import pytest

from app import changelog
from app.services.updates import LATEST_RELEASE_API, UpdateChecker, is_newer

NOTES = """# Changelog

## Unreleased

### New
- Not out yet.

## 0.7.0

### New
- **Bold** thing with `CODE`,
  continued here.
- Second.

### Before you update
- Back up.

### After you update
- Redeploy.

## 0.6.1
- A loose item.

## 0.6.0

### New
- Tags.
"""


def test_releases_parse_with_sections_and_continued_items():
    releases = changelog.parse(NOTES)
    assert [r.version for r in releases] == ["0.7.0", "0.6.1", "0.6.0"]
    new, before, after = releases[0].sections
    assert new.title == "New" and new.items == ["**Bold** thing with `CODE`, continued here.", "Second."]
    assert before.items == ["Back up."] and after.items == ["Redeploy."]
    # After updating, the steps for beforehand are left out.
    assert [s.title for s in changelog.after_update(releases[0])] == ["New", "After you update"]
    assert releases[1].sections[0].title == "" and releases[1].sections[0].items == ["A loose item."]


@pytest.mark.parametrize(
    ("current", "seen", "expected"),
    [
        ("0.7.0", None, ["0.7.0"]),  # an admin who never saw any: just this release
        ("0.7.0", "0.6.0", ["0.7.0", "0.6.1"]),  # skipped a release: both, newest first
        ("0.7.0", "0.7.0", []),
        ("0.6.1", "0.7.0", []),  # went back to an older image
        ("v0.6.1", "0.6.0", ["0.6.1"]),
        ("dev", None, []),
        ("0.8.0", "0.7.0", []),  # a release with no entry has nothing to show
    ],
)
def test_unseen_releases(current, seen, expected):
    releases = changelog.parse(NOTES)
    assert [r.version for r in changelog.unseen(releases, current=current, seen=seen)] == expected


def test_the_shipped_changelog_parses_and_every_release_says_something():
    releases = changelog.releases()
    assert releases
    for release in releases:
        assert release.sections and all(section.items for section in release.sections), release.version


def test_version_comparison():
    assert is_newer("0.10.0", "0.9.9")
    assert not is_newer("0.6.1", "0.6.1")
    assert not is_newer("0.7.0", "dev")


def checker_answering(handler) -> tuple[UpdateChecker, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return UpdateChecker(httpx.AsyncClient(transport=httpx.MockTransport(record)), enabled=True), requests


def test_the_latest_release_is_asked_for_once_and_remembered():
    asyncio.run(_asked_once())


async def _asked_once():
    checker, requests = checker_answering(lambda request: httpx.Response(
        200, json={"tag_name": "v0.7.0", "html_url": "https://github.com/LiftbridgeLabs/feedstash/releases/tag/v0.7.0"}
    ))
    first = await checker.latest()
    again = await checker.latest()
    assert first == again and first.version == "0.7.0" and first.url.endswith("/tag/v0.7.0")
    assert [str(r.url) for r in requests] == [LATEST_RELEASE_API]
    await checker.close()


def test_a_link_elsewhere_is_replaced_and_failures_say_nothing():
    asyncio.run(_links_and_failures())


async def _links_and_failures():
    checker, _ = checker_answering(lambda request: httpx.Response(
        200, json={"tag_name": "v0.7.0", "html_url": "https://evil.example/phish"}
    ))
    assert (await checker.latest()).url == "https://github.com/LiftbridgeLabs/feedstash/releases/tag/v0.7.0"
    await checker.close()

    broken, _ = checker_answering(lambda request: httpx.Response(503))
    assert await broken.latest() is None
    odd, _ = checker_answering(lambda request: httpx.Response(200, json={"tag_name": "nightly"}))
    assert await odd.latest() is None


def test_turned_off_it_never_asks():
    asyncio.run(_turned_off())


async def _turned_off():
    checker, requests = checker_answering(lambda request: httpx.Response(500))
    off = UpdateChecker(None, enabled=False)
    assert await off.latest() is None and requests == []
    await checker.close()
