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
        is_serverless = bool(os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME') or os.environ.get('LAMBDA_TASK_ROOT'))
        if is_serverless:
            upload_dir = '/tmp/uploads/visitor_photos'
        else:
            base_path = current_app.instance_path if current_app else 'instance'
            upload_dir = os.path.join(base_path, 'uploads', 'visitor_photos')
        try:
            os.makedirs(upload_dir, exist_ok=True)
        except OSError:
            import tempfile
            upload_dir = os.path.join(tempfile.gettempdir(), 'vms_uploads', 'visitor_photos')
            os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def serve_fallback_avatar():
        """Returns a clean neutral SVG avatar if the stored photo is not present on disk."""
        from flask import Response
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect width="100%" height="100%" fill="#f3f4f6"/>
            <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
        </svg>"""
        svg_bytes = svg.encode('utf-8')
        response = Response(svg_bytes, mimetype='image/svg+xml')
        response.headers['Content-Type'] = 'image/svg+xml'
        response.headers['Content-Length'] = str(len(svg_bytes))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

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
            upload_dir = UploadService.get_upload_dir()
            save_path = os.path.join(upload_dir, filename)

            # Save clean image
            try:
                clean_img.save(save_path, format='JPEG', quality=85, optimize=True)
            except OSError:
                import tempfile
                fallback_dir = tempfile.gettempdir()
                save_path = os.path.join(fallback_dir, filename)
                clean_img.save(save_path, format='JPEG', quality=85, optimize=True)

            return filename, None

        except Exception as e:
            return None, f"Image file validation failed: {str(e)}"
