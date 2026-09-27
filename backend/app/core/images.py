"""
Validation and normalisation of uploaded visitor photos.

Nothing uploaded is stored as sent. The image is decoded and checked (format,
dimensions, pixel count), then re-encoded as a fresh JPEG. That removes
EXIF metadata (camera, GPS, time) and anything hidden in the file, and the
stored file is always a plain, bounded JPEG.
CPU-bound: async code must call normalize_photo() via asyncio.to_thread.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

ACCEPTED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")          # JPEG, PNG (WebP: RIFF....WEBP)

MIN_WIDTH, MIN_HEIGHT = 160, 120
MAX_SIDE = 4096                 # accepted input
MAX_PIXELS = 12_000_000         # decompression-bomb guard, checked before decoding
STORED_MAX_SIDE = 1024          # stored photos are scaled down to this
JPEG_QUALITY = 85


class InvalidImageError(ValueError):
    """The upload is not an acceptable photo. The message is safe to show to the user."""


@dataclass(frozen=True)
class NormalizedPhoto:
    data: bytes
    width: int
    height: int
    content_type: str = "image/jpeg"


def _has_image_signature(data: bytes) -> bool:
    return data.startswith(_SIGNATURES) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def normalize_photo(data: bytes) -> NormalizedPhoto:
    if not data or not _has_image_signature(data):
        raise InvalidImageError("The photo must be a JPEG, PNG or WebP image.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in _ACCEPTED_FORMATS:
                raise InvalidImageError("The photo must be a JPEG, PNG or WebP image.")
            width, height = img.size                          # read from the header; nothing decoded yet
            if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                raise InvalidImageError(f"The photo is too large (at most {MAX_SIDE} × {MAX_SIDE} pixels).")
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                raise InvalidImageError(f"The photo is too small (at least {MIN_WIDTH} × {MIN_HEIGHT} pixels).")
            if getattr(img, "n_frames", 1) > 1:
                raise InvalidImageError("Animated images are not accepted.")
            img.load()
            photo = ImageOps.exif_transpose(img).convert("RGB")
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, SyntaxError):
        raise InvalidImageError("The photo could not be read. Please take it again.") from None

    photo.thumbnail((STORED_MAX_SIDE, STORED_MAX_SIDE))
    out = io.BytesIO()
    photo.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)     # no EXIF / metadata written
    return NormalizedPhoto(data=out.getvalue(), width=photo.width, height=photo.height)
