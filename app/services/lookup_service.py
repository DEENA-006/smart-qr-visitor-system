import logging
from datetime import datetime, timezone, timedelta
from flask import url_for
from app.extensions import db
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    QRCredential,
    QRCredentialStatus
)
from app.models.user import User, UserRole
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.audit_service import AuditService
from app.services.qr_service import QRService

logger = logging.getLogger(__name__)


class LookupService:
    """
    Dedicated view-only visitor lookup service for Administrators and Faculty.
    Strictly separated from Security Gate operations:
    - Does NOT check in visitors.
    - Does NOT check out visitors.
    - Does NOT consume QR credentials.
    - Enforces role-based permissions (Faculty can only view their own hosted visitors).
    """

    @staticmethod
    def lookup_visitor(raw_input: str, actor_user: User) -> tuple[dict, int]:
        """
        Validates QR code payload or reference code and returns authorized visitor details.
        Returns: (result_dict, http_status_code)
        """
        if not actor_user or not actor_user.is_authenticated:
            return {
                'valid': False,
                'status': 'UNAUTHORIZED',
                'message': 'Authentication required.'
            }, 401

        if actor_user.role not in (UserRole.ADMIN, UserRole.FACULTY):
            return {
                'valid': False,
                'status': 'FORBIDDEN',
                'message': 'Only administrators and authorized faculty members may perform visitor lookups.'
            }, 403

        if not raw_input or not isinstance(raw_input, str):
            return {
                'valid': False,
                'status': 'INVALID_INPUT',
                'message': 'No QR credential token or reference code provided.'
            }, 400

        cleaned = raw_input.strip()

        # 1. Resolve VisitRequest & QRCredential
        req = None
        cred = None

        if cleaned.upper().startswith('REQ-'):
            req = VisitRequest.query.filter_by(public_reference=cleaned.upper()).first()
            if not req:
                return {
                    'valid': False,
                    'status': 'UNKNOWN',
                    'message': f'No registration found for reference code: {cleaned}'
                }, 404
            cred = req.active_credential or req.qr_credentials.first()
        else:
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
                    'status': 'UNKNOWN',
                    'message': 'QR code credential was not recognized or is invalid.'
                }, 404

            req = cred.visit_request
            if not req:
                return {
                    'valid': False,
                    'status': 'UNKNOWN',
                    'message': 'Orphan credential: No visit request linked to this credential.'
                }, 404

        # 2. Enforce Role Authorization
        # Administrators can view any record; Faculty can ONLY view visitors they host
        if actor_user.role == UserRole.FACULTY:
            if req.host_user_id != actor_user.id:
                AuditService.log_event(
                    action='UNAUTHORIZED_ACCESS',
                    entity_type='VISIT_REQUEST',
                    outcome=AuditOutcome.FAILURE,
                    actor_user_id=actor_user.id,
                    entity_reference=req.public_reference,
                    reason=f"Faculty {actor_user.username} denied lookup for visit hosted by user #{req.host_user_id}"
                )
                return {
                    'valid': False,
                    'status': 'FORBIDDEN',
                    'message': 'Access denied: You are only authorized to view details for visitors assigned to your care.'
                }, 403

        # 3. Determine credential and visit state
        # Required states: valid, expired, revoked, not-yet-valid, rejected, unknown, consumed
        now_utc = datetime.now(timezone.utc)
        valid = False

        if req.status == VisitRequestStatus.REJECTED:
            status = 'REJECTED'
            message = 'This registration was rejected.'
        elif cred and cred.status == QRCredentialStatus.REVOKED:
            status = 'REVOKED'
            message = 'This QR credential has been revoked.'
        elif cred and cred.status == QRCredentialStatus.CONSUMED:
            status = 'CONSUMED'
            message = 'This QR credential has already been consumed for a previous campus visit.'
        elif cred and (cred.status == QRCredentialStatus.EXPIRED or cred.expires_at <= now_utc):
            status = 'EXPIRED'
            message = f'This QR credential expired at {cred.expires_at.strftime("%Y-%m-%d %H:%M UTC")}.'
        elif req.planned_start_at and req.planned_start_at > now_utc + timedelta(hours=2):
            status = 'NOT_YET_VALID'
            message = f'Visit is scheduled for a future time: {req.planned_start_at.strftime("%Y-%m-%d %H:%M UTC")}.'
        elif req.status == VisitRequestStatus.PENDING_APPROVAL:
            status = 'PENDING_APPROVAL'
            message = 'This registration request is awaiting review and has not yet been approved.'
        elif req.status == VisitRequestStatus.APPROVED and cred and cred.is_valid_now():
            status = 'VALID'
            message = 'Valid QR pass. Visitor registration is approved and active.'
            valid = True
        else:
            status = req.status
            message = f'Registration status is {req.status.replace("_", " ").lower()}.'

        # 4. Extract authorized visitor details
        active_sess = req.active_session
        visitor_details = {
            'reference': req.public_reference,
            'full_name': req.visitor.full_name if req.visitor else 'Unknown',
            'organization': req.visitor.organization if req.visitor else None,
            'visit_type': req.visit_type,
            'host_name': req.host_user.full_name if req.host_user else 'Campus Host',
            'department': req.department or (req.host_user.department if req.host_user else None),
            'purpose': req.purpose,
            'planned_start_at': req.planned_start_at.isoformat() if req.planned_start_at else None,
            'planned_end_at': req.planned_end_at.isoformat() if req.planned_end_at else None,
            'photo_url': url_for('visitors.serve_visitor_photo', filename=req.photo_filename) if req.photo_filename else None,
            'photo_filename': req.photo_filename,
            'is_currently_on_campus': active_sess is not None,
            'checked_in_at': active_sess.checked_in_at.isoformat() if active_sess else None
        }

        # Audit log the authorized lookup
        AuditService.log_event(
            action='VISITOR_LOOKUP',
            entity_type='VISIT_REQUEST',
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user.id,
            entity_reference=req.public_reference,
            reason=f"Looked up visitor details for {visitor_details['full_name']} (Status: {status})"
        )

        return {
            'valid': valid,
            'status': status,
            'message': message,
            'visitor_details': visitor_details
        }, 200
