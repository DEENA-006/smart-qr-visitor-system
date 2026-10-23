from flask import request
from app.extensions import db
from app.models.audit_log import AuditLog, AuditOutcome


class AuditService:
    @staticmethod
    def log_event(
        action: str,
        entity_type: str,
        outcome: str = AuditOutcome.SUCCESS,
        actor_user_id: int | None = None,
        entity_reference: str | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        commit: bool = True
    ) -> AuditLog:
        """Records an authoritative audit trail entry."""
        if ip_address is None and request:
            try:
                ip_address = request.remote_addr
            except Exception:
                pass
        if user_agent is None and request and hasattr(request, 'user_agent') and request.user_agent:
            try:
                user_agent = str(request.user_agent.string)[:255]
            except Exception:
                pass

        audit_entry = AuditLog(
            action=action,
            entity_type=entity_type,
            outcome=outcome,
            actor_user_id=actor_user_id,
            entity_reference=entity_reference,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent
        )
        if metadata:
            audit_entry.set_metadata(metadata)

        db.session.add(audit_entry)
        if commit:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        return audit_entry
