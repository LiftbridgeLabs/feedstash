"""Uploaded images (stash screenshots and email attachments), stored on disk under random names.

Only real image formats are accepted, identified by their bytes rather than the declared content type
(the Android app uploads everything as `image/*`). SVG is deliberately excluded: it can carry scripts,
and uploads are served from the same origin as the app.
"""

import re
import secrets
from pathlib import Path

from app.errors import InvalidInput

MAX_IMAGE_BYTES = 20 * 1024 * 1024

MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "heic": "image/heic",
}
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}\.(png|jpg|gif|webp|avif|heic)$")


def sniff_image(data: bytes) -> str | None:
    """The image format of `data` ("png", "jpg", ...), or None if it isn't a supported image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic"
    return None


class ImageStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def save(self, data: bytes) -> str:
        """Validates and stores an image. Returns its file name."""
        if not data:
            raise InvalidInput("The image is empty")
        if len(data) > MAX_IMAGE_BYTES:
            raise InvalidInput(f"Images can be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        kind = sniff_image(data)
        if kind is None:
            raise InvalidInput("Only PNG, JPEG, GIF, WebP, AVIF or HEIC images are supported")
        self.directory.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_urlsafe(18)}.{kind}"
        (self.directory / name).write_bytes(data)
        return name

    def path(self, name: str | None) -> Path | None:
        """The file for a stored image name, or None for unknown or malformed names."""
        if not name or not _NAME_RE.match(name):
            return None
        path = self.directory / name
        return path if path.is_file() else None

    def delete(self, name: str | None) -> None:
        path = self.path(name)
        if path is not None:
            path.unlink(missing_ok=True)

    @staticmethod
    def media_type(name: str) -> str:
        return MEDIA_TYPES[name.rsplit(".", 1)[-1]]
