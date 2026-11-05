"""Moving an account to another FeedStash: one .zip with the account's data (account.json) and the pictures its
stash items use (pictures/), and bringing such a file into an account here.

The file comes from an upload, so opening it is careful: a cap on its size, on how much it unpacks to and on the
number of files in it, and every picture checked to be a real image before it's stored.
"""

import json
import tempfile
import zipfile
from pathlib import Path
from typing import IO

from app.clock import now
from app.db import Database
from app.db.repositories import account_transfer as transfer_repo
from app.errors import InvalidInput
from app.images import MAX_IMAGE_BYTES, ImageStore

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024 * 1024
MAX_FILES = 20_000
MAX_PICTURES_BYTES = 1024 * 1024 * 1024  # all the pictures one import may unpack, counted as they're read
NOT_AN_EXPORT = "This file isn't a FeedStash export. Make one with Settings → Feeds → Download everything."


def export_zip(db: Database, images: ImageStore, user_id: int, version: str) -> Path:
    """Writes the account's export to a temporary .zip and returns its path (the caller deletes it)."""
    with db.transaction() as conn:
        data = transfer_repo.export(conn, user_id)
    data["exported_by"] = f"FeedStash {version}"
    data["exported_at"] = now()
    handle = tempfile.NamedTemporaryFile(prefix="feedstash-export-", suffix=".zip", delete=False)
    path = Path(handle.name)
    handle.close()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("account.json", json.dumps(data, ensure_ascii=False))
        for name in sorted(transfer_repo.image_names(data)):
            if (file := images.path(name)) is not None:
                archive.write(file, f"pictures/{name}")
    return path


def import_zip(db: Database, images: ImageStore, user_id: int, upload: IO[bytes]) -> transfer_repo.ImportCounts:
    """Adds an export to the account. Pictures are stored as new files; any that the import doesn't end up using
    (it failed, or the item was already here) are removed again."""
    try:
        archive = zipfile.ZipFile(upload)
    except (zipfile.BadZipFile, OSError):
        raise InvalidInput(NOT_AN_EXPORT) from None
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES:
            raise InvalidInput("This file has too many files in it to be a FeedStash export")
        by_name = {entry.filename: entry for entry in entries}
        info = by_name.get("account.json")
        if info is None:
            raise InvalidInput(NOT_AN_EXPORT)
        if info.file_size > MAX_JSON_BYTES:
            raise InvalidInput("This export is too large to bring in")
        try:
            data = json.loads(_read(archive, info, MAX_JSON_BYTES))
        except (ValueError, UnicodeDecodeError):
            raise InvalidInput(NOT_AN_EXPORT) from None
        transfer_repo.check(data)

        stored: dict[str, str] = {}
        unpacked = 0
        try:
            for name in transfer_repo.image_names(data):
                entry = by_name.get(f"pictures/{name}")
                if entry is None or entry.file_size > MAX_IMAGE_BYTES or "/" in name or ".." in name:
                    continue
                try:
                    picture = _read(archive, entry, MAX_IMAGE_BYTES)
                except InvalidInput:
                    continue  # bigger than its header said: left out
                unpacked += len(picture)
                if unpacked > MAX_PICTURES_BYTES:
                    raise InvalidInput("The pictures in this file add up to more than one import can take")
                try:
                    stored[name] = images.save(picture)
                except InvalidInput:
                    continue  # not a real image: the item comes in without it
        except Exception:
            for new in stored.values():
                images.delete(new)
            raise

    used: set[str] = set()

    def image_for(name: str) -> str | None:
        if new := stored.get(name):
            used.add(new)
        return new

    try:
        with db.transaction() as conn:
            counts = transfer_repo.import_into(conn, user_id, data, now=now(), image_for=image_for)
    except Exception:
        for new in stored.values():
            images.delete(new)
        raise
    for new in set(stored.values()) - used:
        images.delete(new)
    return counts


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """An entry's bytes, refusing to unpack more than `limit` whatever its header claims."""
    with archive.open(info) as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise InvalidInput("Something in this file is too large to bring in")
    return data
