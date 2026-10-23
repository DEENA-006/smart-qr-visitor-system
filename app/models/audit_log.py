import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.types import UTCDateTime


class AuditAction:
    LOGIN_SUCCESS = 'LOGIN_SUCCESS'
    LOGIN_FAILURE = 'LOGIN_FAILURE'
    LOGOUT = 'LOGOUT'
    USER_CREATE = 'USER_CREATE'
    USER_UPDATE = 'USER_UPDATE'
    USER_DEACTIVATE = 'USER_DEACTIVATE'
    PASSWORD_CHANGE = 'PASSWORD_CHANGE'
    SECURITY_CHECK = 'SECURITY_CHECK'
    UNAUTHORIZED_ACCESS = 'UNAUTHORIZED_ACCESS'
    VISIT_APPROVED = 'VISIT_APPROVED'
    VISIT_REJECTED = 'VISIT_REJECTED'
    QR_ISSUED = 'QR_ISSUED'
    QR_REVOKED = 'QR_REVOKED'
    QR_REISSUED = 'QR_REISSUED'
    CHECK_IN = 'CHECK_IN'
    CHECK_OUT = 'CHECK_OUT'
    SESSION_CORRECTED = 'SESSION_CORRECTED'
    REPORT_EXPORTED = 'REPORT_EXPORTED'
    EMERGENCY_LIST_VIEWED = 'EMERGENCY_LIST_VIEWED'
    VISITOR_DETAILS_EDITED = 'VISITOR_DETAILS_EDITED'


class AuditOutcome:
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'
    WARNING = 'WARNING'


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    entity_type = db.Column(db.String(64), nullable=False)
    entity_reference = db.Column(db.String(128), nullable=True)
    outcome = db.Column(db.String(32), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    request_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    def set_metadata(self, data: dict):
        """Safely encodes metadata as JSON, filtering sensitive data."""
        if not data:
            self.metadata_json = None
            return
        # Filter sensitive fields
        sanitized = {k: v for k, v in data.items() if k not in ('password', 'token', 'raw_token', 'secret')}
        self.metadata_json = json.dumps(sanitized)

    def get_metadata(self) -> dict:
        """Parses metadata from JSON."""
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except Exception:
            return {}

    def to_dict(self):
        return {
            'id': self.id,
            'actor_user_id': self.actor_user_id,
            'actor_name': self.actor.full_name if self.actor else 'System / Anonymous',
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_reference': self.entity_reference,
            'outcome': self.outcome,
            'reason': self.reason,
            'metadata': self.get_metadata(),
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<AuditLog id={self.id} action='{self.action}' outcome='{self.outcome}'>"
