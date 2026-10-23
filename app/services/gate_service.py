import re
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    QRCredential,
    QRCredentialStatus,
    VisitSession,
    VisitSessionStatus,
    VisitEvent,
    VisitEventType
)
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, AuditAction, AuditOutcome
from app.services.qr_service import QRService

logger = logging.getLogger(__name__)


class GateService:
    """Service handling gate scanner verification, identity checks, check-in, check-out, and occupancy."""

    @staticmethod
    def verify_credential_or_reference(raw_input: str, actor_user: User) -> dict:
        """
        Validates a scanned QR credential token or a manually entered reference code.
        Does NOT alter session state or consume the credential.
        
        Returns a structured dictionary with verification status and visitor details.
        """
        if not actor_user or not actor_user.has_role(UserRole.SECURITY, UserRole.ADMIN):
            return {
                'valid': False,
                'status': 'UNAUTHORIZED',
                'message': 'Only authorized security and administrative personnel may perform gate verification.'
            }

        if not raw_input or not isinstance(raw_input, str):
            return {
                'valid': False,
                'status': 'INVALID_INPUT',
                'message': 'No credential payload or reference code provided.'
            }

        cleaned = raw_input.strip()

        # Handle manual reference code lookup (e.g., REQ-20261022-XXXXXX)
        if cleaned.upper().startswith('REQ-'):
            req = VisitRequest.query.filter_by(public_reference=cleaned.upper()).first()
            if not req:
                return {
                    'valid': False,
                    'status': 'NOT_FOUND',
                    'message': f'No visit request found for reference code: {cleaned}'
                }

            # Check visit request status
            if req.status == VisitRequestStatus.REJECTED:
                return {
                    'valid': False,
                    'status': 'REJECTED',
                    'message': 'This visit request has been rejected and is not eligible for entry.'
                }
            if req.status == VisitRequestStatus.PENDING_APPROVAL:
                return {
                    'valid': False,
                    'status': 'PENDING_APPROVAL',
                    'message': 'This visit request is still pending host/faculty approval.'
                }
            if req.status == VisitRequestStatus.CANCELLED:
                return {
                    'valid': False,
                    'status': 'CANCELLED',
                    'message': 'This visit request has been cancelled.'
                }
            if req.status != VisitRequestStatus.APPROVED:
                return {
                    'valid': False,
                    'status': req.status,
                    'message': f'Visit request status is {req.status.replace("_", " ").lower()}.'
                }

            # Check active on-campus session
            active_session = req.active_session
            if active_session:
                return {
                    'valid': True,
                    'status': 'ALREADY_CHECKED_IN',
                    'message': 'Visitor is currently checked in on campus.',
                    'request_id': req.id,
                    'session_id': active_session.id,
                    'checked_in_at': active_session.checked_in_at.isoformat() if active_session.checked_in_at else None,
                    'can_check_in': False,
                    'can_check_out': True,
                    'visitor_details': GateService._extract_visitor_details(req)
                }

            # If not checked in, check for active credential
            cred = req.active_credential
            if not cred:
                latest_cred = req.qr_credentials.first()
                if latest_cred and latest_cred.status == QRCredentialStatus.CONSUMED:
                    return {
                        'valid': False,
                        'status': 'CONSUMED',
                        'message': 'QR credential has already been consumed for a prior session.'
                    }
                if latest_cred and latest_cred.status == QRCredentialStatus.REVOKED:
                    return {
                        'valid': False,
                        'status': 'REVOKED',
                        'message': 'QR credential has been revoked by campus staff.'
                    }
                return {
                    'valid': False,
                    'status': 'NO_ACTIVE_CREDENTIAL',
                    'message': 'No active QR credential found for this approved visit.'
                }

            # Validate credential window
            is_usable, err = QRService.is_credential_usable(cred)
            if not is_usable:
                return {
                    'valid': False,
                    'status': 'EXPIRED_OR_OUTSIDE_WINDOW',
                    'message': err,
                    'request_id': req.id,
                    'visitor_details': GateService._extract_visitor_details(req)
                }

            return {
                'valid': True,
                'status': 'VALID',
                'message': 'Valid approved visit. Verify physical photo before admitting visitor.',
                'request_id': req.id,
                'credential_id': cred.id,
                'can_check_in': True,
                'can_check_out': False,
                'visitor_details': GateService._extract_visitor_details(req)
            }

        # Handle scanned QR token payload (VMS:<raw_token> or <raw_token>)
        candidates = [cleaned]
        if cleaned.startswith('VMS:'):
            candidates.append(cleaned[4:].strip())
        else:
            candidates.append(f"VMS:{cleaned}")

        cred = None
        for cand in candidates:
            if not cand:
                continue
            token_hash = QRService.hash_token(cand)
            cred = QRCredential.query.filter_by(token_hash=token_hash).first()
            if cred:
                break

        if not cred:
            return {
                'valid': False,
                'status': 'INVALID_TOKEN',
                'message': 'QR credential token was not recognized or has been tampered with.'
            }

        req = cred.visit_request
        if not req:
            return {
                'valid': False,
                'status': 'ORPHAN_CREDENTIAL',
                'message': 'Credential is not associated with an existing visit request.'
            }

        # Check visit request approval
        if req.status != VisitRequestStatus.APPROVED:
            return {
                'valid': False,
                'status': req.status,
                'message': f'Visit request is {req.status.replace("_", " ").lower()} and cannot be admitted.',
                'visitor_details': GateService._extract_visitor_details(req)
            }

        # Check credential status
        if cred.status == QRCredentialStatus.REVOKED:
            return {
                'valid': False,
                'status': 'REVOKED',
                'message': 'This QR credential was revoked and cannot be used.',
                'visitor_details': GateService._extract_visitor_details(req)
            }

        if cred.status == QRCredentialStatus.CONSUMED:
            active_session = req.active_session
            if active_session:
                return {
                    'valid': True,
                    'status': 'ALREADY_CHECKED_IN',
                    'message': 'Visitor is currently checked in on campus.',
                    'request_id': req.id,
                    'session_id': active_session.id,
                    'checked_in_at': active_session.checked_in_at.isoformat() if active_session.checked_in_at else None,
                    'can_check_in': False,
                    'can_check_out': True,
                    'visitor_details': GateService._extract_visitor_details(req)
                }
            return {
                'valid': False,
                'status': 'CONSUMED',
                'message': 'This single-use QR credential has already been consumed.',
                'visitor_details': GateService._extract_visitor_details(req)
            }

        if cred.status == QRCredentialStatus.EXPIRED:
            return {
                'valid': False,
                'status': 'EXPIRED',
                'message': 'This QR credential has expired.',
                'visitor_details': GateService._extract_visitor_details(req)
            }

        # Check time window
        is_usable, err = QRService.is_credential_usable(cred)
        if not is_usable:
            return {
                'valid': False,
                'status': 'EXPIRED_OR_OUTSIDE_WINDOW',
                'message': err,
                'visitor_details': GateService._extract_visitor_details(req)
            }

        # Check if already active
        active_session = req.active_session
        if active_session:
            return {
                'valid': True,
                'status': 'ALREADY_CHECKED_IN',
                'message': 'Visitor is currently checked in on campus.',
                'request_id': req.id,
                'session_id': active_session.id,
                'checked_in_at': active_session.checked_in_at.isoformat() if active_session.checked_in_at else None,
                'can_check_in': False,
                'can_check_out': True,
                'visitor_details': GateService._extract_visitor_details(req)
            }

        return {
            'valid': True,
            'status': 'VALID',
            'message': 'Valid credential. Verify physical photo before admitting visitor.',
            'request_id': req.id,
            'credential_id': cred.id,
            'can_check_in': True,
            'can_check_out': False,
            'visitor_details': GateService._extract_visitor_details(req)
        }

    @staticmethod
    def _extract_visitor_details(req: VisitRequest) -> dict:
        """Extracts operational visitor details for identity verification and desk editing."""
        return {
            'request_id': req.id,
            'visitor_id': req.visitor_id,
            'reference': req.public_reference,
            'full_name': req.visitor.full_name if req.visitor else 'Unknown',
            'phone': req.visitor.phone if (req.visitor and req.visitor.phone) else '',
            'email': req.visitor.email if (req.visitor and req.visitor.email) else '',
            'organization': req.visitor.organization if (req.visitor and req.visitor.organization) else '',
            'category': req.visit_type,
            'host_name': req.host_user.full_name if req.host_user else 'Department Desk',
            'department': req.department or (req.host_user.department if req.host_user else 'General'),
            'purpose': req.purpose,
            'planned_start_at': req.planned_start_at.isoformat() if req.planned_start_at else None,
            'planned_end_at': req.planned_end_at.isoformat() if req.planned_end_at else None,
            'photo_filename': req.photo_filename,
            'is_possible_duplicate': req.is_possible_duplicate,
            'duplicate_reason': req.duplicate_reason
        }

    @staticmethod
    def check_in(
        request_id: int,
        actor_user: User,
        notes: str = None,
        client_ip: str = None
    ) -> tuple[VisitSession | None, str | None]:
        """
        Performs atomic check-in:
        1. Confirms visit eligibility and absence of existing active session.
        2. Consumes the active QR credential.
        3. Creates an active VisitSession and CHECK_IN VisitEvent.
        4. Logs CHECK_IN audit event.
        """
        if not actor_user or not actor_user.has_role(UserRole.SECURITY, UserRole.ADMIN):
            return None, "Unauthorized: Only security personnel and administrators can perform check-in."

        req = db.session.get(VisitRequest, request_id)
        if not req:
            return None, "Visit request not found."

        if req.status != VisitRequestStatus.APPROVED:
            return None, f"Cannot check in request with status: {req.status}."

        # Check existing active session
        if req.active_session:
            return None, "Visitor already has an active checked-in session on campus."

        # Find active QR credential
        cred = req.active_credential
        if not cred:
            return None, "No active QR credential available for check-in."

        now_utc = datetime.now(timezone.utc)
        is_usable, err = QRService.is_credential_usable(cred, now_utc)
        if not is_usable:
            return None, f"Credential cannot be consumed: {err}"

        try:
            # 1. Consume credential
            cred.status = QRCredentialStatus.CONSUMED
            cred.consumed_at = now_utc

            # 2. Create active session
            session = VisitSession(
                visit_request_id=req.id,
                status=VisitSessionStatus.ACTIVE,
                checked_in_at=now_utc,
                checked_in_by_id=actor_user.id
            )
            db.session.add(session)
            db.session.flush()  # populate session.id

            # 3. Create check-in event
            event = VisitEvent(
                visit_session_id=session.id,
                event_type=VisitEventType.CHECK_IN,
                occurred_at=now_utc,
                recorded_by_id=actor_user.id
            )
            if notes or client_ip:
                event.set_metadata({'notes': notes, 'ip': client_ip})
            db.session.add(event)

            # 4. Audit Log
            log = AuditLog(
                actor_user_id=actor_user.id,
                action=AuditAction.CHECK_IN,
                entity_type='VisitSession',
                entity_reference=f"Session #{session.id} (Req {req.public_reference})",
                outcome=AuditOutcome.SUCCESS,
                reason=notes,
                ip_address=client_ip
            )
            log.set_metadata({
                'session_id': session.id,
                'request_id': req.id,
                'reference': req.public_reference,
                'visitor_name': req.visitor.full_name if req.visitor else 'Unknown'
            })
            db.session.add(log)

            db.session.commit()
            logger.info("Check-in completed: Session #%s for visit %s by user %s", session.id, req.public_reference, actor_user.username)
            return session, None

        except IntegrityError as e:
            db.session.rollback()
            logger.warning("Integrity error during check-in for visit %s: %s", req.public_reference, str(e))
            return None, "Check-in conflict: Visitor may have already been checked in by another gate station."
        except Exception as e:
            db.session.rollback()
            logger.error("Error during check-in for visit %s: %s", req.public_reference, str(e), exc_info=True)
            return None, "An unexpected error occurred during check-in processing."

    @staticmethod
    def check_out(
        session_id: int,
        actor_user: User,
        notes: str = None,
        client_ip: str = None
    ) -> tuple[VisitSession | None, str | None]:
        """
        Performs atomic check-out:
        1. Updates VisitSession to COMPLETED.
        2. Creates CHECK_OUT VisitEvent.
        3. Logs CHECK_OUT audit event.
        """
        if not actor_user or not actor_user.has_role(UserRole.SECURITY, UserRole.ADMIN):
            return None, "Unauthorized: Only security personnel and administrators can perform check-out."

        session = db.session.get(VisitSession, session_id)
        if not session:
            return None, "Active visit session not found."

        if session.status != VisitSessionStatus.ACTIVE:
            return None, f"Cannot check out session with status: {session.status}."

        now_utc = datetime.now(timezone.utc)
        req = session.visit_request

        try:
            # 1. Complete session
            session.status = VisitSessionStatus.COMPLETED
            session.checked_out_at = now_utc
            session.checked_out_by_id = actor_user.id

            # 2. Create check-out event
            event = VisitEvent(
                visit_session_id=session.id,
                event_type=VisitEventType.CHECK_OUT,
                occurred_at=now_utc,
                recorded_by_id=actor_user.id
            )
            if notes or client_ip:
                event.set_metadata({'notes': notes, 'ip': client_ip})
            db.session.add(event)

            # 3. Audit Log
            log = AuditLog(
                actor_user_id=actor_user.id,
                action=AuditAction.CHECK_OUT,
                entity_type='VisitSession',
                entity_reference=f"Session #{session.id} (Req {req.public_reference if req else 'Unknown'})",
                outcome=AuditOutcome.SUCCESS,
                reason=notes,
                ip_address=client_ip
            )
            log.set_metadata({
                'session_id': session.id,
                'request_id': req.id if req else None,
                'reference': req.public_reference if req else None,
                'visitor_name': req.visitor.full_name if (req and req.visitor) else 'Unknown'
            })
            db.session.add(log)

            db.session.commit()
            logger.info("Check-out completed: Session #%s for visit %s by user %s", session.id, req.public_reference if req else 'Unknown', actor_user.username)
            return session, None

        except Exception as e:
            db.session.rollback()
            logger.error("Error during check-out for session #%s: %s", session_id, str(e), exc_info=True)
            return None, "An unexpected error occurred during check-out processing."

    @staticmethod
    def update_visitor_details(
        request_id: int,
        actor_user: User,
        data: dict,
        notes: str = None,
        client_ip: str = None
    ) -> tuple[VisitRequest | None, str | None]:
        """
        Allows authorized security personnel or administrators to correct permitted visitor details:
        - full_name (required, 2-120 chars)
        - phone (optional, up to 32 chars, updates normalized_phone)
        - email (optional, valid email syntax, up to 120 chars)
        - organization (optional, up to 120 chars)
        - purpose (required, 2-255 chars)

        Security, Privacy & Integrity Guarantees:
        1. Role check: only SECURITY and ADMIN accounts can perform corrections.
        2. Mass assignment protection: protected fields (id, status, hashes, role, timestamps) are strictly immutable.
        3. Audit Trail: logs actor, timestamp, IP, changed fields list, and old/new values.
        4. Atomic transaction: commits or rolls back cleanly.
        5. Does NOT check in or check out the visitor.
        6. Does NOT alter approval status or QR validity.
        """
        if not actor_user or not actor_user.has_role(UserRole.SECURITY, UserRole.ADMIN):
            return None, "Unauthorized: Only security personnel and administrators can edit visitor details."

        req = db.session.get(VisitRequest, request_id)
        if not req:
            return None, "Visit request record not found."

        visitor = req.visitor
        if not visitor:
            return None, "Associated visitor master record not found."

        # Extract and validate permitted editable fields
        full_name = data.get('full_name')
        if full_name is not None:
            full_name = str(full_name).strip()
            if not full_name or len(full_name) < 2:
                return None, "Visitor full name is required (minimum 2 characters)."
            if len(full_name) > 120:
                return None, "Visitor full name must not exceed 120 characters."

        purpose = data.get('purpose')
        if purpose is not None:
            purpose = str(purpose).strip()
            if not purpose or len(purpose) < 2:
                return None, "Visit purpose is required (minimum 2 characters)."
            if len(purpose) > 255:
                return None, "Visit purpose must not exceed 255 characters."

        phone = data.get('phone')
        if phone is not None:
            phone = str(phone).strip()
            if not phone:
                return None, "Phone number is required."
            if len(phone) > 32:
                return None, "Phone number must not exceed 32 characters."
            digits = re.sub(r'\D', '', phone)
            if len(digits) < 7:
                return None, "Phone number must contain at least 7 digits."

        email = data.get('email')
        if email is not None:
            email = str(email).strip()
            if email:
                if len(email) > 120:
                    return None, "Email address must not exceed 120 characters."
                if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
                    return None, "Invalid email address format."

        organization = data.get('organization')
        if organization is not None:
            organization = str(organization).strip()
            if len(organization) > 120:
                return None, "Organization must not exceed 120 characters."

        # Track changes for audit trail
        changed_fields = []
        old_values = {}
        new_values = {}
        now_utc = datetime.now(timezone.utc)

        try:
            if full_name is not None and full_name != visitor.full_name:
                changed_fields.append('full_name')
                old_values['full_name'] = visitor.full_name
                new_values['full_name'] = full_name
                visitor.full_name = full_name

            if phone is not None and phone != (visitor.phone or ''):
                changed_fields.append('phone')
                old_values['phone'] = visitor.phone or ''
                new_values['phone'] = phone
                visitor.phone = phone if phone else None
                from app.services.duplicate_service import DuplicateService
                visitor.normalized_phone = DuplicateService.normalize_phone(phone) if phone else None

            if email is not None and email.lower() != (visitor.email or '').lower():
                changed_fields.append('email')
                old_values['email'] = visitor.email or ''
                new_values['email'] = email
                visitor.email = email if email else None

            if organization is not None and organization != (visitor.organization or ''):
                changed_fields.append('organization')
                old_values['organization'] = visitor.organization or ''
                new_values['organization'] = organization
                visitor.organization = organization if organization else None

            if purpose is not None and purpose != req.purpose:
                changed_fields.append('purpose')
                old_values['purpose'] = req.purpose
                new_values['purpose'] = purpose
                req.purpose = purpose

            if changed_fields:
                visitor.updated_at = now_utc
                req.updated_at = now_utc

                # Log AUDIT event
                log = AuditLog(
                    actor_user_id=actor_user.id,
                    action=AuditAction.VISITOR_DETAILS_EDITED,
                    entity_type='VisitRequest',
                    entity_reference=req.public_reference,
                    outcome=AuditOutcome.SUCCESS,
                    reason=notes or f"Security desk correction: {', '.join(changed_fields)}",
                    ip_address=client_ip
                )
                log.set_metadata({
                    'request_id': req.id,
                    'reference': req.public_reference,
                    'visitor_id': visitor.id,
                    'changed_fields': changed_fields,
                    'old_values': old_values,
                    'new_values': new_values,
                    'notes': notes
                })
                db.session.add(log)

            db.session.commit()
            logger.info(
                "Visitor details updated for request %s by user %s (fields: %s)",
                req.public_reference,
                actor_user.username,
                ', '.join(changed_fields) if changed_fields else 'none'
            )
            return req, None

        except Exception as e:
            db.session.rollback()
            logger.error("Error updating visitor details for request #%s: %s", request_id, str(e), exc_info=True)
            return None, "An unexpected database error occurred while updating visitor details."

    @staticmethod
    def get_current_occupancy() -> int:
        """Returns the real-time count of visitors currently checked in on campus."""
        return VisitSession.query.filter_by(status=VisitSessionStatus.ACTIVE).count()

    @staticmethod
    def get_active_sessions(limit: int = 100) -> list[VisitSession]:
        """Returns active sessions ordered by arrival time."""
        return VisitSession.query.filter_by(
            status=VisitSessionStatus.ACTIVE
        ).order_by(VisitSession.checked_in_at.desc()).limit(limit).all()

    @staticmethod
    def get_security_kpis() -> dict:
        """Calculates security gate KPIs for today."""
        now_utc = datetime.now(timezone.utc)
        today_start_utc = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)

        current_occupancy = VisitSession.query.filter_by(status=VisitSessionStatus.ACTIVE).count()

        today_checkins = VisitSession.query.filter(
            VisitSession.checked_in_at >= today_start_utc
        ).count()

        today_checkouts = VisitSession.query.filter(
            VisitSession.checked_out_at >= today_start_utc,
            VisitSession.status == VisitSessionStatus.COMPLETED
        ).count()

        # Flagged records: active sessions > 12 hours old or past planned_end_at by 1h
        twelve_hours_ago = now_utc - timedelta(hours=12)
        flagged_records = VisitSession.query.filter(
            VisitSession.status == VisitSessionStatus.ACTIVE,
            VisitSession.checked_in_at < twelve_hours_ago
        ).count()

        return {
            'current_occupancy': current_occupancy,
            'today_checkins': today_checkins,
            'today_checkouts': today_checkouts,
            'flagged_records': flagged_records
        }

    @staticmethod
    def correct_session(
        session_id: int,
        actor_user: User,
        checked_in_at: datetime,
        checked_out_at: datetime | None,
        status: str,
        reason: str,
        client_ip: str = None
    ) -> tuple[VisitSession | None, str | None]:
        """
        Administratively corrects or updates a visit session (timestamps, status, notes).
        Ensures strict audit logging and creates an APPROVED_CORRECTION VisitEvent.
        """
        if not actor_user or not actor_user.has_role(UserRole.ADMIN):
            return None, "Unauthorized: Only administrators can modify session records."

        session = db.session.get(VisitSession, session_id)
        if not session:
            return None, "Visit session not found."

        if not reason or not reason.strip():
            return None, "A valid reason for the administrative correction is required."

        if status not in (VisitSessionStatus.ACTIVE, VisitSessionStatus.COMPLETED):
            return None, f"Invalid session status: {status}."

        if not checked_in_at:
            return None, "Check-in timestamp is required."

        # Normalize to UTC
        if checked_in_at.tzinfo is None:
            checked_in_at = checked_in_at.replace(tzinfo=timezone.utc)
        else:
            checked_in_at = checked_in_at.astimezone(timezone.utc)

        if status == VisitSessionStatus.COMPLETED:
            if not checked_out_at:
                return None, "Departure check-out timestamp is required for completed sessions."
            if checked_out_at.tzinfo is None:
                checked_out_at = checked_out_at.replace(tzinfo=timezone.utc)
            else:
                checked_out_at = checked_out_at.astimezone(timezone.utc)

            if checked_out_at < checked_in_at:
                return None, "Departure timestamp cannot be earlier than check-in timestamp."
        else:
            # ACTIVE status
            # Check if another active session already exists for this visit request
            other_active = VisitSession.query.filter(
                VisitSession.visit_request_id == session.visit_request_id,
                VisitSession.id != session.id,
                VisitSession.status == VisitSessionStatus.ACTIVE
            ).first()
            if other_active:
                return None, f"Another active session (#{other_active.id}) already exists for this visit request."
            checked_out_at = None

        try:
            old_state = {
                'status': session.status,
                'checked_in_at': session.checked_in_at.isoformat() if session.checked_in_at else None,
                'checked_out_at': session.checked_out_at.isoformat() if session.checked_out_at else None,
            }

            session.status = status
            session.checked_in_at = checked_in_at
            session.checked_out_at = checked_out_at

            # Add APPROVED_CORRECTION VisitEvent
            event = VisitEvent(
                visit_session_id=session.id,
                event_type=VisitEventType.APPROVED_CORRECTION,
                occurred_at=datetime.now(timezone.utc),
                recorded_by_id=actor_user.id,
                correction_reason=reason.strip()
            )
            event.set_metadata({
                'old_state': old_state,
                'new_state': {
                    'status': status,
                    'checked_in_at': checked_in_at.isoformat(),
                    'checked_out_at': checked_out_at.isoformat() if checked_out_at else None,
                },
                'client_ip': client_ip
            })
            db.session.add(event)

            # Audit log
            log = AuditLog(
                actor_user_id=actor_user.id,
                action=AuditAction.SESSION_CORRECTED,
                entity_type='VisitSession',
                entity_reference=f"Session #{session.id} (Req {session.visit_request.public_reference if session.visit_request else 'Unknown'})",
                outcome=AuditOutcome.SUCCESS,
                reason=reason.strip(),
                ip_address=client_ip
            )
            log.set_metadata({
                'session_id': session.id,
                'old_state': old_state,
                'new_state': {
                    'status': status,
                    'checked_in_at': checked_in_at.isoformat(),
                    'checked_out_at': checked_out_at.isoformat() if checked_out_at else None,
                }
            })
            db.session.add(log)

            db.session.commit()
            logger.info("Admin %s corrected VisitSession #%s: status=%s, reason=%s", actor_user.username, session.id, status, reason)
            return session, None
        except Exception as e:
            db.session.rollback()
            logger.error("Error correcting session #%s: %s", session_id, str(e), exc_info=True)
            return None, "An unexpected error occurred while saving session corrections."
