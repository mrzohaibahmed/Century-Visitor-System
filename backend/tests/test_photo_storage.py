"""The private photo folder (CG_PHOTO_DIR): start-up check, readiness, and no silent re-creation."""
import shutil

import pytest

from app.db.migrate import apply_schema
from app.main import create_app
from app.services.photos import PhotoStorageError, check_photo_dir
from tests.conftest import make_settings
from tests.test_images import image_bytes
from tests.test_visitors import new_visitor

pytestmark = pytest.mark.anyio


def test_production_refuses_to_start_without_the_photo_folder(tmp_path):
    settings = make_settings(environment="production", photo_dir=tmp_path / "missing")
    with pytest.raises(PhotoStorageError, match="does not exist") as error:
        check_photo_dir(settings, create=False)
    assert str(tmp_path) not in str(error.value)                  # no path in the message
    assert not (tmp_path / "missing").exists()                    # and nothing was created


def test_production_refuses_a_file_instead_of_a_folder(tmp_path):
    (tmp_path / "photos").write_text("not a folder")
    with pytest.raises(PhotoStorageError, match="not a folder"):
        check_photo_dir(make_settings(environment="production", photo_dir=tmp_path / "photos"), create=False)


def test_an_existing_writable_folder_is_accepted_and_left_clean(tmp_path):
    check_photo_dir(make_settings(environment="production", photo_dir=tmp_path), create=False)
    assert list(tmp_path.iterdir()) == []                         # the write test file is removed


def test_development_creates_the_folder(tmp_path):
    check_photo_dir(make_settings(photo_dir=tmp_path / "new" / "photos"), create=True)
    assert (tmp_path / "new" / "photos").is_dir()


async def test_the_production_app_does_not_start_without_the_folder(tmp_path):
    app = create_app(make_settings(environment="production", photo_dir=tmp_path / "missing"))
    with pytest.raises(PhotoStorageError):
        async with app.router.lifespan_context(app):
            pass


async def test_a_vanished_folder_is_reported_and_not_recreated(harness, settings, guard):
    await apply_schema(harness.db)
    visitor = await new_visitor(guard)
    shutil.rmtree(settings.photo_dir)                             # e.g. the photo drive is disconnected
    ready = await harness.client().get("/api/v1/health/ready")
    assert ready.status_code == 503 and ready.json()["checks"]["photo_storage"] == "unavailable"
    r = await guard.post(f"/api/v1/visitors/{visitor['id']}/photo", content=image_bytes(),
                         headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "photo_storage_unavailable"
    assert "Continue without a photo" in r.json()["error"]["message"]
    assert str(settings.photo_dir) not in r.text
    assert not settings.photo_dir.exists()                        # photos did not go to a new, empty folder
    assert await harness.db.photos.count_documents({}) == 0
