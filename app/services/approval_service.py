from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Union

from app.extensions import db
from app.models.user import User, UserRole
from app.models.visit import (
    VisitRequest,
    VisitRequestStatus,
    ApprovalDecision,
    ApprovalDecisionType,
)
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class ApprovalService:
    """Business service governing visitor request reviews, state transitions, and approval auditing."""

    @staticmethod
    def can_user_review_request(actor_user: Optional[User], request_obj: VisitRequest) -> Tuple[bool, Optional[str]]:
        """
        Validates whether the given user is authorized to approve/reject the visit request.
        - Administrators can review any request.
        - Faculty can review ONLY requests assigned to them as host.
        - Security staff, unauthenticated, and other roles are strictly rejected.
        """
        if actor_user is None or not getattr(actor_user, 'is_authenticated', False):
            return False, "Authentication required to review visitor requests."

        role = getattr(actor_user, 'role', None)
        if role == UserRole.ADMIN:
            return True, None

        if role == UserRole.FACULTY:
            if getattr(request_obj, 'host_user_id', None) == getattr(actor_user, 'id', None):
                return True, None
            return False, "You are only authorized to review visitor requests assigned to you."

        return False, "Your account role is not authorized to review visitor requests."

    @staticmethod
    def approve_request(
        request_id: int,
        actor_user: Optional[User],
        actor_ip: Optional[str] = None
    ) -> Tuple[Optional[VisitRequest], Optional[str]]:
        """
        Approves an eligible PENDING_APPROVAL visit request within a single transaction.
        Updates VisitRequest fields, creates ApprovalDecision, and writes an AuditLog entry atomically.
        """
        if actor_user is None or not getattr(actor_user, 'is_authenticated', False):
            return None, "Authentication required to review visitor requests."

        req = db.session.get(VisitRequest, request_id)
        if not req:
            return None, "Visit request not found."

        # Verify review authorization
        can_review, auth_err = ApprovalService.can_user_review_request(actor_user, req)
        if not can_review:
            return None, auth_err

        # Verify state transition
        if req.status != VisitRequestStatus.PENDING_APPROVAL:
            if req.status == VisitRequestStatus.APPROVED:
                return None, "This visit request has already been approved."
            elif req.status == VisitRequestStatus.REJECTED:
                return None, "This visit request has already been rejected and cannot be approved."
            else:
                return None, f"Cannot approve visit request in status '{req.status}'."

        now_utc = datetime.now(timezone.utc)
        actor_user_id: int = getattr(actor_user, 'id')
        actor_username: str = getattr(actor_user, 'username', 'user')

        # Atomic transition
        req.status = VisitRequestStatus.APPROVED
        req.approved_at = now_utc
        req.decided_by_id = actor_user_id
        req.rejection_reason = None

        decision = ApprovalDecision(
            visit_request_id=req.id,
            actor_user_id=actor_user_id,
            decision=ApprovalDecisionType.APPROVED,
            reason=None,
            created_at=now_utc
        )
        db.session.add(decision)

        AuditService.log_event(
            action=AuditAction.VISIT_APPROVED,
            entity_type='VISIT_REQUEST',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user_id,
            ip_address=actor_ip,
            metadata={
                'visit_type': req.visit_type,
                'visitor_id': req.visitor_id,
                'host_user_id': req.host_user_id
            },
            commit=False
        )

        # Issue QR Credential atomically as part of the approval transaction
        from app.services.qr_service import QRService

        cred, raw_token, qr_err = QRService.issue_credential(
            request_id=req.id,
            actor_user=actor_user,
            commit=False
        )
        if qr_err:
            db.session.rollback()
            return None, f"Approval aborted: {qr_err}"

        try:
            db.session.commit()
            logger.info(
                f"Visit request {req.public_reference} approved and QR credential issued by user {actor_username} (id={actor_user_id})"
            )
            return req, None
        except Exception as e:
            db.session.rollback()
            if cred and getattr(cred, 'token_hash', None):
                QRService.remove_qr_image(cred.token_hash)
            logger.error(f"Failed to commit visit approval for {req.id}: {e}")
            return None, "A database error occurred while processing the approval decision."

    @staticmethod
    def reject_request(
        request_id: int,
        actor_user: Optional[User],
        reason: Optional[str] = None,
        actor_ip: Optional[str] = None
    ) -> Tuple[Optional[VisitRequest], Optional[str]]:
        """
        Rejects an eligible PENDING_APPROVAL visit request with a mandatory reason within a single transaction.
        Updates VisitRequest fields, creates ApprovalDecision, and writes an AuditLog entry atomically.
        """
        if actor_user is None or not getattr(actor_user, 'is_authenticated', False):
            return None, "Authentication required to review visitor requests."

        req = db.session.get(VisitRequest, request_id)
        if not req:
            return None, "Visit request not found."

        # Verify review authorization
        can_review, auth_err = ApprovalService.can_user_review_request(actor_user, req)
        if not can_review:
            return None, auth_err

        # Verify state transition
        if req.status != VisitRequestStatus.PENDING_APPROVAL:
            if req.status == VisitRequestStatus.REJECTED:
                return None, "This visit request has already been rejected."
            elif req.status == VisitRequestStatus.APPROVED:
                return None, "This visit request has already been approved and cannot be rejected."
            else:
                return None, f"Cannot reject visit request in status '{req.status}'."

        # Validate rejection reason
        clean_reason = (reason or '').strip()
        if not clean_reason:
            return None, "A rejection reason is required."
        if len(clean_reason) > 255:
            return None, "Rejection reason must not exceed 255 characters."

        now_utc = datetime.now(timezone.utc)
        actor_user_id: int = getattr(actor_user, 'id')
        actor_username: str = getattr(actor_user, 'username', 'user')

        # Atomic transition
        req.status = VisitRequestStatus.REJECTED
        req.rejected_at = now_utc
        req.decided_by_id = actor_user_id
        req.rejection_reason = clean_reason

        decision = ApprovalDecision(
            visit_request_id=req.id,
            actor_user_id=actor_user_id,
            decision=ApprovalDecisionType.REJECTED,
            reason=clean_reason,
            created_at=now_utc
        )
        db.session.add(decision)

        AuditService.log_event(
            action=AuditAction.VISIT_REJECTED,
            entity_type='VISIT_REQUEST',
            entity_reference=req.public_reference,
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=actor_user_id,
            reason=clean_reason,
            ip_address=actor_ip,
            metadata={
                'visit_type': req.visit_type,
                'visitor_id': req.visitor_id,
                'host_user_id': req.host_user_id
            },
            commit=False
        )

        try:
            db.session.commit()
            logger.info(
                f"Visit request {req.public_reference} rejected by user {actor_username} (reason: {clean_reason})"
            )
            return req, None
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to commit visit rejection for {req.id}: {e}")
            return None, "A database error occurred while processing the rejection decision."

    @staticmethod
    def get_faculty_requests(faculty_user: User, status_filter: Optional[str] = None) -> List[VisitRequest]:
        """Returns visit requests assigned to the specified faculty member, optionally filtered by status."""
        stmt = db.select(VisitRequest).where(VisitRequest.host_user_id == faculty_user.id)
        if status_filter and status_filter.upper() in VisitRequestStatus.ALL:
            stmt = stmt.where(VisitRequest.status == status_filter.upper())
        stmt = stmt.order_by(VisitRequest.submitted_at.desc())
        return list(db.session.scalars(stmt).all())

    @staticmethod
    def get_admin_requests(
        status_filter: Optional[str] = None,
        visit_type_filter: Optional[str] = None,
        host_user_id: Optional[int] = None
    ) -> List[VisitRequest]:
        """Returns visit requests across all campus hosts with optional status and visit-type filters."""
        stmt = db.select(VisitRequest)
        if status_filter and status_filter.upper() in VisitRequestStatus.ALL:
            stmt = stmt.where(VisitRequest.status == status_filter.upper())
        if visit_type_filter:
            stmt = stmt.where(VisitRequest.visit_type == visit_type_filter.upper())
        if host_user_id:
            stmt = stmt.where(VisitRequest.host_user_id == host_user_id)
        stmt = stmt.order_by(VisitRequest.submitted_at.desc())
        return list(db.session.scalars(stmt).all())
