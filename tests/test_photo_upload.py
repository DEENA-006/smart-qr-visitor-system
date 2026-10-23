"""Unit tests for hardened photo upload security and validation."""
import io
import os
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from app.services.upload_service import UploadService, MAX_PHOTO_SIZE_BYTES


def create_test_image(format='JPEG', color='blue', size=(100, 100)):
    """Helper to generate binary image in memory."""
    buf = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    return buf


def test_valid_jpeg_upload(app):
    with app.app_context():
        buf = create_test_image('JPEG')
        fs = FileStorage(stream=buf, filename="visitor.jpg", content_type="image/jpeg")

        filename, err = UploadService.process_and_save_photo(fs)
        assert err is None
        assert filename is not None
        assert filename.endswith('.jpg')

        # Check file exists and is valid
        save_path = os.path.join(UploadService.get_upload_dir(), filename)
        assert os.path.exists(save_path)

        # Cleanup
        if os.path.exists(save_path):
            os.remove(save_path)


def test_valid_png_upload_re_encoded(app):
    with app.app_context():
        buf = create_test_image('PNG')
        fs = FileStorage(stream=buf, filename="passport.png", content_type="image/png")

        filename, err = UploadService.process_and_save_photo(fs)
        assert err is None
        assert filename is not None

        # Verify saved file is sanitized JPEG
        save_path = os.path.join(UploadService.get_upload_dir(), filename)
        assert os.path.exists(save_path)
        with Image.open(save_path) as img:
            assert img.format == 'JPEG'

        if os.path.exists(save_path):
            os.remove(save_path)


def test_unsupported_file_extension(app):
    with app.app_context():
        buf = io.BytesIO(b"dummy script content")
        fs = FileStorage(stream=buf, filename="script.sh", content_type="application/x-sh")

        filename, err = UploadService.process_and_save_photo(fs)
        assert filename is None
        assert "Unsupported file extension" in err


def test_empty_photo_file(app):
    with app.app_context():
        buf = io.BytesIO(b"")
        fs = FileStorage(stream=buf, filename="empty.jpg", content_type="image/jpeg")

        filename, err = UploadService.process_and_save_photo(fs)
        assert filename is None
        assert "is empty" in err


def test_oversized_photo_file(app):
    with app.app_context():
        # Create a buffer exceeding 5MB
        oversized_data = b"X" * (MAX_PHOTO_SIZE_BYTES + 1024)
        buf = io.BytesIO(oversized_data)
        fs = FileStorage(stream=buf, filename="huge.jpg", content_type="image/jpeg")

        filename, err = UploadService.process_and_save_photo(fs)
        assert filename is None
        assert "exceeds the 5MB maximum" in err


def test_disguised_text_fails_pillow_verification(app):
    """File has .jpg extension but contains plain text / HTML instead of valid image bytes."""
    with app.app_context():
        buf = io.BytesIO(b"<!DOCTYPE html><html><body><h1>Not an image file</h1></body></html>")
        fs = FileStorage(stream=buf, filename="avatar.jpg", content_type="image/jpeg")

        filename, err = UploadService.process_and_save_photo(fs)
        assert filename is None
        assert "validation failed" in err.lower()


def test_serverless_upload_dir_uses_tmp(monkeypatch, app):
    monkeypatch.setenv("VERCEL", "1")
    with app.app_context():
        upload_dir = UploadService.get_upload_dir()
        assert upload_dir.startswith("/tmp") or "tmp" in upload_dir.lower()


def test_serve_fallback_avatar():
    response = UploadService.serve_fallback_avatar()
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    assert b"<svg" in response.data
