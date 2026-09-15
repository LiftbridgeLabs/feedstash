import pytest

from app import images as images_module
from app.errors import InvalidInput
from app.images import ImageStore, sniff_image
from support.images import JPEG, PNG


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (PNG, "png"),
        (JPEG, "jpg"),
        (b"GIF89a\x01\x00\x01\x00", "gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00", "heic"),
        (b"\x00\x00\x00\x1cftypavif\x00\x00", "avif"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', None),
        (b"<html><body>hi</body></html>", None),
        (b"", None),
    ],
)
def test_sniff_image(data, kind):
    assert sniff_image(data) == kind


def test_images_get_random_names_and_only_stored_files_are_served(tmp_path):
    store = ImageStore(tmp_path / "uploads")
    name = store.save(PNG)
    assert name.endswith(".png")
    assert store.path(name).read_bytes() == PNG
    assert store.media_type(name) == "image/png"
    assert store.save(PNG) != name

    for bad in ("../secret.key", "..\\evil.png", "x.png", name.replace(".png", ".svg"), "", None):
        assert store.path(bad) is None

    store.delete(name)
    assert store.path(name) is None
    store.delete(name)  # deleting twice is fine


def test_non_images_and_oversized_images_are_rejected(tmp_path, monkeypatch):
    store = ImageStore(tmp_path / "uploads")
    with pytest.raises(InvalidInput):
        store.save(b"<html>not an image</html>")
    with pytest.raises(InvalidInput):
        store.save(b"")
    monkeypatch.setattr(images_module, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(InvalidInput, match="at most"):
        store.save(PNG)
    assert not (tmp_path / "uploads").exists() or not any((tmp_path / "uploads").iterdir())
