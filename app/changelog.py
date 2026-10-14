"""Release notes from CHANGELOG.md, which ships in the Docker image: which releases an admin hasn't seen yet.

No I/O beyond reading the file once; comparing versions is all string work.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    sections: list[Section] = field(default_factory=list)


def version_key(version: str | None) -> tuple[int, int, int] | None:
    """(major, minor, patch) for "0.6.2" or "v0.6.2"; None for "dev", "Unreleased" and anything else."""
    match = _VERSION.match((version or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def parse(text: str) -> list[Release]:
    """`## 0.6.2` starts a release, `### New` a section, `- ` an item (continued on indented lines). Releases
    without a version number, like "Unreleased", are left out."""
    releases: list[Release] = []
    release: Release | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            heading = line[3:].strip()
            release = Release(heading) if version_key(heading) else None
            if release:
                releases.append(release)
        elif release is not None:
            _add_line(release, line)
    return releases


def _add_line(release: Release, line: str) -> None:
    sections = release.sections
    if line.startswith("### "):
        sections.append(Section(line[4:].strip()))
    elif line.startswith("- "):
        if not sections:
            sections.append(Section(""))
        sections[-1].items.append(line[2:].strip())
    elif line.startswith(" ") and line.strip() and sections and sections[-1].items:
        sections[-1].items[-1] += " " + line.strip()


@cache
def releases() -> list[Release]:
    try:
        return parse(CHANGELOG_PATH.read_text(encoding="utf-8"))
    except OSError:
        return []


def unseen(all_releases: list[Release], *, current: str, seen: str | None) -> list[Release]:
    """The releases after `seen` up to and including `current`, newest first. With nothing seen yet, just the current
    one; on a development build, none."""
    now = version_key(current)
    if now is None:
        return []
    last = version_key(seen)
    if last is not None and last >= now:
        return []
    picked = []
    for release in all_releases:
        key = version_key(release.version)
        if key is None or key > now:
            continue
        if (last is None and key == now) or (last is not None and key > last):
            picked.append(release)
    return sorted(picked, key=lambda release: version_key(release.version), reverse=True)
