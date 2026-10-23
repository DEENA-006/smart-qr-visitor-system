from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Union

import qrcode
from PIL import Image
from flask import current_app

from app.extensions import db
from app.models.user import User, UserRole
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    QRCredential,
    QRCredentialStatus,
)
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class QRService:
    """Service governing secure QR credential lifecycle, token hashing, validity, and image rendering."""

    TOKEN_PREFIX = "VMS:"

    @staticmethod
    def get_qr_dir() -> Path:
        """Returns the filesystem directory used for storing generated QR images."""
        is_serverless = bool(os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME') or os.environ.get('LAMBDA_TASK_ROOT'))
        if is_serverless:
            qr_dir = Path("/tmp/uploads/qr_codes")
        else:
            base_instance = Path(current_app.instance_path) if current_app else Path("instance")
            qr_dir = base_instance / "uploads" / "qr_codes"
        try:
            qr_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            import tempfile
            qr_dir = Path(tempfile.gettempdir()) / "vms_uploads" / "qr_codes"
            qr_dir.mkdir(parents=True, exist_ok=True)
        return qr_dir

    @staticmethod
    def generate_token() -> str:
        """
        Generates an opaque, cryptographically random token.
        Format: VMS:<32-byte-urlsafe-string> (256 bits of high entropy).
        Contains no visitor PII, IDs, or timestamps.
        """
        raw = secrets.token_urlsafe(32)
        return f"{QRService.TOKEN_PREFIX}{raw}"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """
        Computes SHA-256 digest of the raw token string.
        Only this 64-character hex digest is persisted in the database.
        """
        clean_token = (raw_token or '').strip()
        return hashlib.sha256(clean_token.encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_validity(
        request_obj: VisitRequest,
        now_utc: Optional[datetime] = None
    ) -> Tuple[Optional[datetime], Optional[datetime], Optional[str]]:
        """
        Calculates credential validity window based on planned visit dates and system configuration.
        Returns (issued_at, expires_at, error_message).
        """
        now = now_utc or datetime.now(timezone.utc)
        validity_minutes = int(
            current_app.config.get('QR_VALIDITY_MINUTES', 120) if current_app else 120
        )

        start_at = request_obj.planned_start_at
        end_at = request_obj.planned_end_at

        # Both start and end dates provided
        if start_at and end_at:
            if end_at <= start_at:
                return None, None, "Invalid visit date range: departure is before or equal to arrival."
            if end_at <= now:
                return None, None, "Cannot issue credential: visit planned end time is already in the past."
            issued_at = now
            expires_at = end_at
            return issued_at, expires_at, None

        # Only start date provided
        if start_at and not end_at:
            if start_at < now - timedelta(hours=24):
                return None, None, "Cannot issue credential: visit planned start date has already passed."
            issued_at = now
            expires_at = max(start_at, now) + timedelta(minutes=validity_minutes)
            return issued_at, expires_at, None

        # No dates provided: use now + configurable validity window
        issued_at = now
        expires_at = now + timedelta(minutes=validity_minutes)
        return issued_at, expires_at, None

    @staticmethod
    def is_credential_usable(
        credential: QRCredential,
        target_time: Optional[datetime] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Authoritative server-side check of whether a credential can be used for campus entry.
        Checks status, expiry timestamp, visit approval, and arrival window.
        """
        if not credential:
            return False, "Credential does not exist."

        now = target_time or datetime.now(timezone.utc)

        if credential.status != QRCredentialStatus.ACTIVE:
            return False, f"Credential is not active (status: {credential.status})."

        if credential.expires_at <= now:
            return False, "Credential has expired."

        req = credential.visit_request
        if not req or req.status != VisitRequestStatus.APPROVED:
            return False, f"Associated visit request is not approved (status: {req.status if req else 'UNKNOWN'})."

        # Check visit start window (allowed entry up to 60 minutes before scheduled arrival)
        if req.planned_start_at:
            earliest_allowed = req.planned_start_at - timedelta(minutes=60)
            if now < earliest_allowed:
                return False, "Visit window has not started yet. Early entry is not permitted."

        return True, None

    @staticmethod
    def generate_qr_image_bytes(payload: str) -> bytes:
        """Renders payload string into an in-memory PNG QR code image."""
        try:
            from qrcode.constants import ERROR_CORRECT_M
            err_level = ERROR_CORRECT_M
        except Exception:
            err_level = 0

        qr = qrcode.QRCode(
            version=None,
            error_correction=err_level,
            box_size=8,
            border=3,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        # Convert to 24-bit RGB mode so all viewers (Windows Photos, Mac Preview, iOS/Android) can open the downloaded image
        if hasattr(img, 'convert'):
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    @staticmethod
    def save_qr_image(token_hash: str, raw_token: str) -> Path:
        """Generates and writes the QR image to the local filesystem."""
        qr_dir = QRService.get_qr_dir()
        file_path = qr_dir / f"{token_hash}.png"
        img_bytes = QRService.generate_qr_image_bytes(raw_token)
        try:
            with open(file_path, "wb") as f:
                f.write(img_bytes)
        except OSError:
            import tempfile
            file_path = Path(tempfile.gettempdir()) / f"{token_hash}.png"
            with open(file_path, "wb") as f:
                f.write(img_bytes)
        return file_path

    @staticmethod
    def get_qr_image_bytes(token_hash: str) -> Optional[bytes]:
        """Reads stored QR image bytes from disk if present."""
        qr_dir = QRService.get_qr_dir()
        file_path = qr_dir / f"{token_hash}.png"
        if file_path.exists():
            try:
                with open(file_path, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Error reading QR image {file_path}: {e}")
        import tempfile
        fallback_path = Path(tempfile.gettempdir()) / f"{token_hash}.png"
        if fallback_path.exists():
            try:
                with open(fallback_path, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Error reading fallback QR image {fallback_path}: {e}")
        return None

    @staticmethod
    def remove_qr_image(token_hash: str) -> None:
        """Deletes stored QR image from disk if present."""
        try:
            qr_dir = QRService.get_qr_dir()
            file_path = qr_dir / f"{token_hash}.png"
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.warning(f"Could not remove QR image for hash {token_hash}: {e}")

    @staticmethod
    def issue_credential(
        request_id: int,
        actor_user: Optional[User] = None,
        commit: bool = True
    ) -> Tuple[Optional[QRCredential], Optional[str], Optional[str]]:
        """
        Issues a new active QRCredential for an eligible APPROVED visit request.
        Returns (credential, raw_token, error_message).
        Only the SHA-256 hash is persisted in the database.
        """
        req = db.session.get(VisitRequest, request_id)
        if not req:
            return None, None, "Visit request not found."

        if req.status != VisitRequestStatus.APPROVED:
            return None, None, f"Cannot issue QR credential for request in status '{req.status}'. Request must be APPROVED."

        # Check for existing active and usable credential
        active_cred = req.active_credential
        if active_cred and active_cred.is_valid_now():
            return None, None, "An active QR credential already exists for this visit request."

        # Calculate validity dates
        issued_at, expires_at, err = QRService.calculate_validity(req)
        if err:
            return None, None, err

        # Generate opaque token and hash
        raw_token = QRService.generate_token()
        token_hash = QRService.hash_token(raw_token)

        cred = QRCredential(
            visit_request_id=req.id,
            token_hash=token_hash,
            status=QRCredentialStatus.ACTIVE,
            issued_at=issued_at,
            expires_at=expires_at
        )
        db.session.add(cred)

        # Save image file to disk
        created_file_path = None
        try:
            created_file_path = QRService.save_qr_image(token_hash, raw_token)
        except Exception as e:
            logger.error(f"Failed to generate QR image for request {req.id}: {e}")
            return None, None, "Failed to render QR code image."

        # Record audit event (NEVER log the raw token)
        AuditService.log_event(
            action=AuditAction.QR_ISSUED,
            entity_type='QR_CREDENTIAL',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=getattr(actor_user, 'id', None),
            metadata={
                'visit_request_id': req.id,
                'expires_at': expires_at.isoformat() if expires_at else None,
                'token_hash_prefix': token_hash[:8]
            },
            commit=False
        )

        if commit:
            try:
                db.session.commit()
                logger.info(f"QR credential issued for visit {req.public_reference} (expires: {expires_at})")
                return cred, raw_token, None
            except Exception as e:
                db.session.rollback()
                if created_file_path and created_file_path.exists():
                    created_file_path.unlink(missing_ok=True)
                logger.error(f"Failed to commit QR issuance for request {req.id}: {e}")
                return None, None, "A database error occurred while issuing the QR credential."

        return cred, raw_token, None

    @staticmethod
    def revoke_credential(
        credential_id: int,
        actor_user: User,
        reason: Optional[str] = None,
        commit: bool = True
    ) -> Tuple[Optional[QRCredential], Optional[str]]:
        """
        Revokes an existing credential.
        Authorized only for Administrators or the assigned host faculty.
        """
        if not actor_user or not getattr(actor_user, 'is_authenticated', False):
            return None, "Authentication required to revoke credentials."

        cred = db.session.get(QRCredential, credential_id)
        if not cred:
            return None, "Credential not found."

        req = cred.visit_request
        # Check authorization
        is_admin = actor_user.role == UserRole.ADMIN
        is_host = actor_user.role == UserRole.FACULTY and (req and req.host_user_id == actor_user.id)
        if not (is_admin or is_host):
            return None, "You are not authorized to revoke credentials for this visit request."

        if cred.status == QRCredentialStatus.REVOKED:
            return None, "Credential has already been revoked."

        if cred.status == QRCredentialStatus.CONSUMED:
            return None, "Cannot revoke an already-consumed credential."

        now_utc = datetime.now(timezone.utc)
        cred.status = QRCredentialStatus.REVOKED
        cred.revoked_at = now_utc
        cred.revoked_by_id = actor_user.id

        # Remove image from disk
        QRService.remove_qr_image(cred.token_hash)

        clean_reason = (reason or '').strip() or "Revoked by authorized staff"
        AuditService.log_event(
            action=AuditAction.QR_REVOKED,
            entity_type='QR_CREDENTIAL',
            entity_reference=req.public_reference if req else f"CRED-{cred.id}",
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user.id,
            reason=clean_reason,
            metadata={
                'credential_id': cred.id,
                'visit_request_id': cred.visit_request_id
            },
            commit=False
        )

        if commit:
            try:
                db.session.commit()
                logger.info(f"Credential {cred.id} revoked by user {actor_user.username}")
                return cred, None
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed to commit credential revocation for {cred.id}: {e}")
                return None, "A database error occurred while revoking the credential."

        return cred, None

    @staticmethod
    def reissue_credential(
        request_id: int,
        actor_user: User,
        reason: Optional[str] = None
    ) -> Tuple[Optional[QRCredential], Optional[str], Optional[str]]:
        """
        Atomically revokes any active credential and issues a replacement.
        Ensures failed operations do not leave two active credentials or orphan files.
        Returns (new_credential, new_raw_token, error_message).
        """
        if not actor_user or not getattr(actor_user, 'is_authenticated', False):
            return None, None, "Authentication required to reissue credentials."

        # Check system reissue policy
        allow_reissue = True
        if current_app:
            allow_reissue = current_app.config.get('QR_ALLOW_REISSUE', True)
        if not allow_reissue:
            return None, None, "Credential reissue is disabled by system policy."

        req = db.session.get(VisitRequest, request_id)
        if not req:
            return None, None, "Visit request not found."

        # Check authorization
        is_admin = actor_user.role == UserRole.ADMIN
        is_host = actor_user.role == UserRole.FACULTY and req.host_user_id == actor_user.id
        if not (is_admin or is_host):
            return None, None, "You are not authorized to reissue credentials for this visit request."

        if req.status != VisitRequestStatus.APPROVED:
            return None, None, f"Cannot reissue credential for visit in status '{req.status}'. Must be APPROVED."

        # Calculate new validity window
        issued_at, expires_at, val_err = QRService.calculate_validity(req)
        if val_err:
            return None, None, val_err

        now_utc = datetime.now(timezone.utc)
        clean_reason = (reason or '').strip() or "Reissued by authorized staff"

        # Revoke all currently active credentials for this request
        old_hashes_to_clean = []
        active_creds = QRCredential.query.filter_by(
            visit_request_id=req.id,
            status=QRCredentialStatus.ACTIVE
        ).all()
        for old_cred in active_creds:
            old_cred.status = QRCredentialStatus.REVOKED
            old_cred.revoked_at = now_utc
            old_cred.revoked_by_id = actor_user.id
            old_hashes_to_clean.append(old_cred.token_hash)

        # Generate new token and hash
        new_raw_token = QRService.generate_token()
        new_token_hash = QRService.hash_token(new_raw_token)

        new_cred = QRCredential(
            visit_request_id=req.id,
            token_hash=new_token_hash,
            status=QRCredentialStatus.ACTIVE,
            issued_at=issued_at,
            expires_at=expires_at
        )
        db.session.add(new_cred)

        # Render new image
        new_image_path = None
        try:
            new_image_path = QRService.save_qr_image(new_token_hash, new_raw_token)
        except Exception as e:
            logger.error(f"Failed to generate replacement QR image for request {req.id}: {e}")
            return None, None, "Failed to render replacement QR code image."

        # Audit event for reissue
        AuditService.log_event(
            action=AuditAction.QR_REISSUED,
            entity_type='QR_CREDENTIAL',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user.id,
            reason=clean_reason,
            metadata={
                'visit_request_id': req.id,
                'new_token_hash_prefix': new_token_hash[:8],
                'revoked_count': len(active_creds),
                'expires_at': expires_at.isoformat() if expires_at else None
            },
            commit=False
        )

        try:
            db.session.commit()
            # Clean up old image files from disk after commit
            for h in old_hashes_to_clean:
                QRService.remove_qr_image(h)
            logger.info(f"QR credential successfully reissued for {req.public_reference} by user {actor_user.username}")
            return new_cred, new_raw_token, None
        except Exception as e:
            db.session.rollback()
            if new_image_path and new_image_path.exists():
                new_image_path.unlink(missing_ok=True)
            logger.error(f"Failed to commit credential reissue for request {req.id}: {e}")
            return None, None, "A database error occurred while reissuing the credential."

    @staticmethod
    def validate_token(
        raw_token: str,
        target_time: Optional[datetime] = None
    ) -> Tuple[Optional[QRCredential], Optional[str]]:
        """
        Validates an incoming raw token string against the stored SHA-256 hash.
        Performs constant-time comparison and server-side policy verification.
        Returns (credential, error_message).
        """
        clean_token = (raw_token or '').strip()
        if not clean_token:
            return None, "No QR token provided."

        if not clean_token.startswith(QRService.TOKEN_PREFIX):
            return None, "Invalid token format."

        submitted_hash = QRService.hash_token(clean_token)
        cred = QRCredential.query.filter_by(token_hash=submitted_hash).first()
        if not cred:
            return None, "Invalid or unrecognized QR credential."

        # Constant-time comparison
        if not hmac.compare_digest(cred.token_hash, submitted_hash):
            return None, "Token verification failed."

        # Server-side validity check
        is_usable, err = QRService.is_credential_usable(cred, target_time=target_time)
        if not is_usable:
            return None, err

        return cred, None
