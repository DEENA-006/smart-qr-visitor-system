import io
import os
import uuid
from PIL import Image
from flask import current_app
from werkzeug.datastructures import FileStorage


ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_PIL_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class UploadService:
    @staticmethod
    def get_upload_dir() -> str:
        """Returns the absolute path to visitor photos storage directory."""
        upload_dir = os.path.join(current_app.instance_path, 'uploads', 'visitor_photos')
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def process_and_save_photo(file: FileStorage) -> tuple[str | None, str | None]:
        """
        Validates, sanitizes, and stores uploaded visitor photos.
        Enforces:
        1. Non-empty file upload.
        2. Strict extension whitelist.
        3. 5MB hard payload size limit during read.
        4. Deep binary Pillow image format verification (defends against polyglots/scripts).
        5. Re-encoding to clean JPEG to strip malicious EXIF/metadata payloads.
        6. UUID storage in non-public instance directory.
        """
        if not file or not file.filename:
            return None, "No photo file provided."

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return None, f"Unsupported file extension '{ext}'. Allowed: JPG, PNG, WEBP."

        # Read content while checking size limit
        content = file.read()
        if len(content) == 0:
            return None, "Uploaded photo file is empty."

        if len(content) > MAX_PHOTO_SIZE_BYTES:
            return None, f"Photo exceeds the 5MB maximum size limit (received {len(content) / (1024 * 1024):.2f}MB)."

        # Deep format and integrity verification via Pillow
        try:
            # 1. Verify binary image structure
            verify_stream = io.BytesIO(content)
            img = Image.open(verify_stream)
            img_format = img.format

            if img_format not in ALLOWED_PIL_FORMATS:
                return None, f"Unsupported image binary format '{img_format}'."

            img.verify()  # Raises exception if file is corrupted or disguised script

            # 2. Re-open and re-encode to sanitize metadata and strip potential exploits
            reopen_stream = io.BytesIO(content)
            clean_img = Image.open(reopen_stream)

            # Convert RGBA / palette images to RGB for safe JPEG serialization
            if clean_img.mode in ('RGBA', 'LA', 'P'):
                clean_img = clean_img.convert('RGB')
            elif clean_img.mode != 'RGB':
                clean_img = clean_img.convert('RGB')

            # Generate random UUID filename
            filename = f"{uuid.uuid4().hex}.jpg"
            save_path = os.path.join(UploadService.get_upload_dir(), filename)

            # Save clean image
            clean_img.save(save_path, format='JPEG', quality=85, optimize=True)

            return filename, None

        except Exception as e:
            return None, f"Image file validation failed: {str(e)}"
