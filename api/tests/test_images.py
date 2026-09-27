"""Photo validation and re-encoding (no database)."""
import io

import pytest
from PIL import Image

from app.core.images import STORED_MAX_SIDE, InvalidImageError, normalize_photo


def image_bytes(size=(640, 480), fmt="JPEG", color=(90, 120, 150), mode="RGB", **save) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color if mode == "RGB" else 1).save(out, format=fmt, **save)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepted_formats_are_stored_as_jpeg(fmt):
    photo = normalize_photo(image_bytes(fmt=fmt))
    assert photo.data.startswith(b"\xff\xd8\xff") and photo.content_type == "image/jpeg"
    assert (photo.width, photo.height) == (640, 480)


def test_large_photos_are_scaled_down():
    photo = normalize_photo(image_bytes(size=(2000, 1500)))
    assert max(photo.width, photo.height) == STORED_MAX_SIDE and photo.width / photo.height == pytest.approx(4 / 3)


def test_metadata_is_removed():
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"               # Make
    exif[0x9003] = "2026:09:27 10:00:00"     # DateTimeOriginal
    source = image_bytes(exif=exif.tobytes())
    assert b"SecretCam" in source
    stored = normalize_photo(source).data
    assert b"SecretCam" not in stored and b"Exif" not in stored


def test_anything_appended_to_the_file_is_dropped():
    source = image_bytes() + b"<script>alert(1)</script>"
    assert b"<script>" not in normalize_photo(source).data


@pytest.mark.parametrize("data,message", [
    (b"", "JPEG, PNG or WebP"),
    (b"hello, this is not an image", "JPEG, PNG or WebP"),
    (b"GIF89a" + b"\x00" * 100, "JPEG, PNG or WebP"),
    (image_bytes()[:400], "could not be read"),                                  # truncated
    (image_bytes(size=(100, 80)), "too small"),
    (image_bytes(size=(5000, 200), fmt="PNG"), "too large"),
    (image_bytes(size=(3900, 3900), fmt="PNG", mode="1"), "too large"),          # 15 M pixels: bomb guard
])
def test_unacceptable_uploads_are_refused(data, message):
    with pytest.raises(InvalidImageError, match=message):
        normalize_photo(data)


def test_a_disguised_file_is_refused():
    # JPEG signature followed by rubbish: the signature alone is not trusted.
    with pytest.raises(InvalidImageError):
        normalize_photo(b"\xff\xd8\xff\xe0" + b"not really a jpeg" * 20)
