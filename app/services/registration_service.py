import json
import uuid
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models.user import User, UserRole
from app.models.visitor import Visitor
from app.models.registration_form import RegistrationForm, FormVersion, FormVersionStatus
from app.models.visit import VisitRequest, VisitResponse, VisitRequestStatus
from app.models.visit_type import VisitType
from app.models.audit_log import AuditOutcome
from app.services.audit_service import AuditService
from app.services.form_service import FormService
from app.services.upload_service import UploadService
from app.services.duplicate_service import DuplicateService


class RegistrationService:
    @staticmethod
    def generate_reference(prefix: str = "REQ") -> str:
        """Generates a unique, high-entropy public reference e.g., REQ-20261021-9F3A."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        hex_suffix = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{date_str}-{hex_suffix}"

    @staticmethod
    def validate_host_id(host_user_id: int | None) -> tuple[User | None, str | None]:
        """
        Validates host server-side.
        Guarantees:
        - Host user must exist.
        - Host account must be active.
        - Host role must be FACULTY or ADMIN. Security staff cannot host visits.
        """
        if not host_user_id:
            return None, "A host must be selected for this visit."

        try:
            host_id = int(host_user_id)
        except (ValueError, TypeError):
            return None, "Invalid host identifier provided."

        host = db.session.get(User, host_id)
        if not host:
            return None, "The selected host account does not exist."

        if not host.is_active:
            return None, "The selected host account is currently inactive."

        if host.role not in (UserRole.FACULTY, UserRole.ADMIN):
            return None, f"Users with role '{host.role}' cannot be assigned as visit hosts."

        return host, None

    @staticmethod
    def register_visitor(
        visit_type: str | None = None,
        full_name: str = '',
        email: str | None = None,
        phone: str | None = None,
        organization: str | None = None,
        host_user_id: int | None = None,
        purpose: str = '',
        planned_start_at: datetime | str | None = None,
        planned_end_at: datetime | str | None = None,
        dynamic_responses: dict | None = None,
        photo_file=None,
        actor_ip: str | None = None,
        form_identifier: str | None = None
    ) -> tuple[VisitRequest | None, str | None]:
        """
        Processes visitor registration submission transactionally.
        Enforces:
        - Valid visit type or public form token resolution.
        - Active published form version association.
        - Server-side host validation (FACULTY / ADMIN, is_active=True).
        - Dynamic schema constraints (required fields, dropdown options, email/tel format).
        - Hardened photo processing via UploadService.
        - Non-blocking duplicate detection via DuplicateService.
        """
        if form_identifier:
            form, version = FormService.get_form_by_token_or_type(form_identifier)
            if not form or not version or version.status != FormVersionStatus.PUBLISHED:
                return None, f"No published registration form is currently available for '{form_identifier}'."
            visit_type = form.visit_type
        else:
            if not visit_type or visit_type not in VisitType.ALL:
                return None, f"Invalid visit type '{visit_type}'."
            # Verify active published form version
            form, version = FormService.get_active_published_form(visit_type)
            if not form or not version or version.status != FormVersionStatus.PUBLISHED:
                return None, f"No published registration form is currently available for visit type '{visit_type}'."

        # Validate core fields
        full_name = (full_name or '').strip()
        if not full_name or len(full_name) < 2:
            return None, "Full name is required (minimum 2 characters)."
        if len(full_name) > 120:
            return None, "Full name must not exceed 120 characters."

        purpose = (purpose or '').strip()
        if not purpose:
            purpose = f"Registration for {form.name}" if form else "Campus Visitor Registration"

        # Validate host
        host, host_err = RegistrationService.validate_host_id(host_user_id)
        if host_err:
            return None, host_err

        # Validate schedule arrival and departure times
        now_utc = datetime.now(timezone.utc)
        if planned_start_at:
            if isinstance(planned_start_at, str):
                try:
                    dt = datetime.fromisoformat(planned_start_at.strip())
                    planned_start_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except Exception:
                    return None, "Invalid format for expected arrival date and time."
            elif planned_start_at.tzinfo is None:
                planned_start_at = planned_start_at.replace(tzinfo=timezone.utc)
            if planned_start_at < now_utc - timedelta(minutes=15):
                return None, "Expected arrival date and time cannot be in the past."

        if planned_end_at:
            if isinstance(planned_end_at, str):
                try:
                    dt = datetime.fromisoformat(planned_end_at.strip())
                    planned_end_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except Exception:
                    return None, "Invalid format for expected departure date and time."
            elif planned_end_at.tzinfo is None:
                planned_end_at = planned_end_at.replace(tzinfo=timezone.utc)
            if planned_start_at and planned_end_at < planned_start_at:
                return None, "Expected departure date and time cannot be earlier than arrival time."

        # Validate dynamic form schema responses
        schema = version.get_schema()
        dynamic_responses = dynamic_responses or {}
        dynamic_answers = {}
        for field in schema:
            f_key = field.get('field_key')
            f_label = field.get('field_label') or field.get('label') or f_key
            f_type = field.get('field_type')
            is_req = field.get('is_required', False)
            val = dynamic_responses.get(f_key)

            if f_type in ('image', 'file'):
                if val and hasattr(val, 'filename') and val.filename:
                    saved_img, img_err = UploadService.process_and_save_photo(val)
                    if img_err:
                        return None, f"Image upload error for '{f_label}': {img_err}"
                    dynamic_answers[f_key] = saved_img
                elif isinstance(val, str) and val.strip():
                    dynamic_answers[f_key] = val.strip()
                elif is_req:
                    return None, f"Required image '{f_label}' was not provided."
                else:
                    dynamic_answers[f_key] = None
                continue

            if is_req and (val is None or str(val).strip() == ''):
                return None, f"Required field '{f_label}' was not provided."

            if val is not None and str(val).strip() != '':
                val_str = str(val).strip()
                if f_type in ('select', 'dropdown'):
                    allowed_options = field.get('options', [])
                    if val_str not in allowed_options:
                        return None, f"Selected value '{val_str}' is not an allowed option for '{f_label}'."
                elif f_type == 'email':
                    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', val_str):
                        return None, f"Invalid email format for '{f_label}'."
                elif f_type == 'tel':
                    digits = re.sub(r'\D', '', val_str)
                    if len(digits) < 7:
                        return None, f"Phone number for '{f_label}' requires at least 7 digits."
                dynamic_answers[f_key] = val_str
            else:
                dynamic_answers[f_key] = None

        # Photo upload handling
        photo_filename = None
        if photo_file and getattr(photo_file, 'filename', None):
            saved_name, upload_err = UploadService.process_and_save_photo(photo_file)
            if upload_err:
                return None, f"Photo upload error: {upload_err}"
            photo_filename = saved_name

        # Non-blocking duplicate and risk evaluation
        eval_result = DuplicateService.evaluate_registration(
            phone=phone,
            email=email,
            full_name=full_name,
            planned_start_at=planned_start_at,
            host_user_id=host.id
        )
        is_dup = eval_result['is_flagged']
        dup_reason = eval_result['reason']

        try:
            # 1. Create or match Visitor record
            norm_phone = DuplicateService.normalize_phone(phone)
            clean_email = (email or '').strip().lower() if email else None

            visitor = None
            if norm_phone:
                visitor = Visitor.query.filter_by(normalized_phone=norm_phone).first()
            if not visitor and clean_email:
                visitor = Visitor.query.filter(func.lower(Visitor.email) == clean_email).first()

            if not visitor:
                visitor = Visitor(
                    public_reference=RegistrationService.generate_reference(prefix="VIS"),
                    full_name=full_name,
                    phone=phone.strip() if phone else None,
                    normalized_phone=norm_phone if norm_phone else None,
                    email=clean_email,
                    organization=organization.strip() if organization else None
                )
                db.session.add(visitor)
                db.session.flush()
            else:
                # Update existing visitor contact details
                visitor.full_name = full_name
                if phone:
                    visitor.phone = phone.strip()
                    visitor.normalized_phone = norm_phone
                if clean_email:
                    visitor.email = clean_email
                if organization:
                    visitor.organization = organization.strip()

            # 2. Create VisitRequest
            req_ref = RegistrationService.generate_reference(prefix="REQ")
            visit_request = VisitRequest(
                public_reference=req_ref,
                visitor_id=visitor.id,
                form_version_id=version.id,
                visit_type=visit_type,
                host_user_id=host.id,
                department=host.department,
                purpose=purpose,
                planned_start_at=planned_start_at,
                planned_end_at=planned_end_at,
                photo_filename=photo_filename,
                is_possible_duplicate=is_dup,
                duplicate_reason=dup_reason,
                status=VisitRequestStatus.PENDING_APPROVAL
            )
            db.session.add(visit_request)
            db.session.flush()

            # 3. Create VisitResponse with dynamic answers
            visit_response = VisitResponse(
                visit_request_id=visit_request.id,
                form_version_id=version.id,
                response_json=json.dumps(dynamic_answers)
            )
            db.session.add(visit_response)
            db.session.commit()

            AuditService.log_event(
                action='VISITOR_REGISTER',
                entity_type='VISIT_REQUEST',
                outcome=AuditOutcome.SUCCESS,
                entity_reference=visit_request.public_reference,
                ip_address=actor_ip,
                reason=f"Registered visitor {visitor.full_name} for host {host.username} ({visit_type})"
            )

            return visit_request, None

        except Exception as e:
            db.session.rollback()
            return None, f"Failed to record visitor registration: {str(e)}"
