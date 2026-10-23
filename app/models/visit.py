import json
import uuid
from datetime import datetime, timezone
from app.extensions import db
from app.models.types import UTCDateTime


class VisitRequestStatus:
    PENDING_APPROVAL = 'PENDING_APPROVAL'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    CANCELLED = 'CANCELLED'
    EXPIRED = 'EXPIRED'

    ALL = (PENDING_APPROVAL, APPROVED, REJECTED, CANCELLED, EXPIRED)


class VisitRequest(db.Model):
    __tablename__ = 'visit_requests'

    id = db.Column(db.Integer, primary_key=True)
    public_reference = db.Column(db.String(32), unique=True, nullable=False, index=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey('visitors.id', ondelete='CASCADE'), nullable=False, index=True)
    form_version_id = db.Column(db.Integer, db.ForeignKey('form_versions.id', ondelete='RESTRICT'), nullable=False, index=True)
    visit_type = db.Column(db.String(32), nullable=False, index=True)
    host_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    department = db.Column(db.String(100), nullable=True)
    purpose = db.Column(db.String(255), nullable=False)
    planned_start_at = db.Column(UTCDateTime, nullable=True)
    planned_end_at = db.Column(UTCDateTime, nullable=True)
    photo_filename = db.Column(db.String(255), nullable=True)
    is_possible_duplicate = db.Column(db.Boolean, default=False, nullable=False, index=True)
    duplicate_reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), default=VisitRequestStatus.PENDING_APPROVAL, nullable=False, index=True)
    submitted_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Approval audit fields
    approved_at = db.Column(UTCDateTime, nullable=True)
    rejected_at = db.Column(UTCDateTime, nullable=True)
    decided_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    rejection_reason = db.Column(db.String(255), nullable=True)

    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    form_version = db.relationship('FormVersion', foreign_keys=[form_version_id])
    host_user = db.relationship('User', foreign_keys=[host_user_id])
    decided_by = db.relationship('User', foreign_keys=[decided_by_id])
    response = db.relationship('VisitResponse', backref='visit_request', uselist=False, cascade='all, delete-orphan')
    decisions = db.relationship('ApprovalDecision', backref='visit_request', cascade='all, delete-orphan', order_by='ApprovalDecision.created_at.desc()', lazy='dynamic')
    qr_credentials = db.relationship('QRCredential', back_populates='visit_request', cascade='all, delete-orphan', order_by='QRCredential.issued_at.desc()', lazy='dynamic')
    sessions = db.relationship('VisitSession', backref='visit_request', cascade='all, delete-orphan', order_by='VisitSession.created_at.desc()', lazy='dynamic')

    @classmethod
    def generate_reference(cls) -> str:
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        rand_str = uuid.uuid4().hex[:6].upper()
        return f"REQ-{date_str}-{rand_str}"

    @property
    def active_session(self):
        """Returns currently active check-in session if present."""
        return self.sessions.filter_by(status=VisitSessionStatus.ACTIVE).first()

    @property
    def active_credential(self):
        """Returns currently active QR credential if present."""
        return self.qr_credentials.filter_by(status=QRCredentialStatus.ACTIVE).first()

    @property
    def host(self):
        """Convenience alias for host_user."""
        return self.host_user

    def to_dict(self):
        return {
            'id': self.id,
            'public_reference': self.public_reference,
            'visitor_id': self.visitor_id,
            'visitor_name': self.visitor.full_name if self.visitor else None,
            'visit_type': self.visit_type,
            'host_user_id': self.host_user_id,
            'host_name': self.host_user.full_name if self.host_user else None,
            'department': self.department,
            'purpose': self.purpose,
            'planned_start_at': self.planned_start_at.isoformat() if self.planned_start_at else None,
            'planned_end_at': self.planned_end_at.isoformat() if self.planned_end_at else None,
            'photo_filename': self.photo_filename,
            'is_possible_duplicate': self.is_possible_duplicate,
            'duplicate_reason': self.duplicate_reason,
            'status': self.status,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejected_at': self.rejected_at.isoformat() if self.rejected_at else None,
            'decided_by_id': self.decided_by_id,
            'decided_by_name': self.decided_by.full_name if self.decided_by else None,
            'rejection_reason': self.rejection_reason,
            'form_version_id': self.form_version_id
        }

    def __repr__(self):
        return f"<VisitRequest id={self.id} ref='{self.public_reference}' status='{self.status}'>"


class VisitResponse(db.Model):
    __tablename__ = 'visit_responses'

    id = db.Column(db.Integer, primary_key=True)
    visit_request_id = db.Column(db.Integer, db.ForeignKey('visit_requests.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    form_version_id = db.Column(db.Integer, db.ForeignKey('form_versions.id', ondelete='RESTRICT'), nullable=False, index=True)
    response_json = db.Column(db.Text, nullable=False, default='{}')
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    form_version = db.relationship('FormVersion', foreign_keys=[form_version_id])

    def get_responses(self) -> dict:
        if not self.response_json:
            return {}
        try:
            return json.loads(self.response_json)
        except Exception:
            return {}

    def set_responses(self, data: dict):
        self.response_json = json.dumps(data) if data else '{}'

    def to_dict(self):
        return {
            'id': self.id,
            'visit_request_id': self.visit_request_id,
            'form_version_id': self.form_version_id,
            'responses': self.get_responses(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<VisitResponse id={self.id} request_id={self.visit_request_id}>"


class ApprovalDecisionType:
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    ALL = (APPROVED, REJECTED)


class ApprovalDecision(db.Model):
    __tablename__ = 'approval_decisions'

    id = db.Column(db.Integer, primary_key=True)
    visit_request_id = db.Column(db.Integer, db.ForeignKey('visit_requests.id', ondelete='CASCADE'), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    decision = db.Column(db.String(20), nullable=False, index=True)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    actor_user = db.relationship('User', foreign_keys=[actor_user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'visit_request_id': self.visit_request_id,
            'actor_user_id': self.actor_user_id,
            'actor_user_name': self.actor_user.full_name if self.actor_user else None,
            'decision': self.decision,
            'reason': self.reason,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<ApprovalDecision id={self.id} request_id={self.visit_request_id} decision='{self.decision}'>"


class QRCredentialStatus:
    ACTIVE = 'ACTIVE'
    CONSUMED = 'CONSUMED'
    REVOKED = 'REVOKED'
    EXPIRED = 'EXPIRED'
    ALL = (ACTIVE, CONSUMED, REVOKED, EXPIRED)


class QRCredential(db.Model):
    __tablename__ = 'qr_credentials'

    id = db.Column(db.Integer, primary_key=True)
    visit_request_id = db.Column(db.Integer, db.ForeignKey('visit_requests.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default=QRCredentialStatus.ACTIVE, nullable=False, index=True)
    issued_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    expires_at = db.Column(UTCDateTime, nullable=False, index=True)
    revoked_at = db.Column(UTCDateTime, nullable=True)
    revoked_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    consumed_at = db.Column(UTCDateTime, nullable=True)
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    revoked_by = db.relationship('User', foreign_keys=[revoked_by_id])
    visit_request = db.relationship('VisitRequest', foreign_keys=[visit_request_id], back_populates='qr_credentials')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def is_valid_now(self) -> bool:
        now_utc = datetime.now(timezone.utc)
        return self.status == QRCredentialStatus.ACTIVE and self.expires_at > now_utc

    def to_dict(self):
        return {
            'id': self.id,
            'visit_request_id': self.visit_request_id,
            'token_hash': self.token_hash,
            'status': self.status,
            'issued_at': self.issued_at.isoformat() if self.issued_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'consumed_at': self.consumed_at.isoformat() if self.consumed_at else None,
            'is_valid': self.is_valid_now()
        }

    def __repr__(self):
        return f"<QRCredential id={self.id} request_id={self.visit_request_id} status='{self.status}'>"


class VisitSessionStatus:
    ACTIVE = 'ACTIVE'
    COMPLETED = 'COMPLETED'
    ALL = (ACTIVE, COMPLETED)


class VisitSession(db.Model):
    __tablename__ = 'visit_sessions'

    id = db.Column(db.Integer, primary_key=True)
    visit_request_id = db.Column(db.Integer, db.ForeignKey('visit_requests.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(20), default=VisitSessionStatus.ACTIVE, nullable=False, index=True)
    checked_in_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    checked_in_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    checked_out_at = db.Column(UTCDateTime, nullable=True)
    checked_out_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        db.Index(
            'uq_visit_sessions_single_active',
            'visit_request_id',
            unique=True,
            sqlite_where=(db.column('status') == VisitSessionStatus.ACTIVE),
            postgresql_where=(db.column('status') == VisitSessionStatus.ACTIVE)
        ),
    )

    checked_in_by = db.relationship('User', foreign_keys=[checked_in_by_id])
    checked_out_by = db.relationship('User', foreign_keys=[checked_out_by_id])
    events = db.relationship('VisitEvent', backref='visit_session', cascade='all, delete-orphan', order_by='VisitEvent.occurred_at.asc()', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'visit_request_id': self.visit_request_id,
            'status': self.status,
            'checked_in_at': self.checked_in_at.isoformat() if self.checked_in_at else None,
            'checked_in_by_id': self.checked_in_by_id,
            'checked_in_by_name': self.checked_in_by.full_name if self.checked_in_by else None,
            'checked_out_at': self.checked_out_at.isoformat() if self.checked_out_at else None,
            'checked_out_by_id': self.checked_out_by_id,
            'checked_out_by_name': self.checked_out_by.full_name if self.checked_out_by else None
        }

    def __repr__(self):
        return f"<VisitSession id={self.id} request_id={self.visit_request_id} status='{self.status}'>"


class VisitEventType:
    CHECK_IN = 'CHECK_IN'
    CHECK_OUT = 'CHECK_OUT'
    APPROVED_CORRECTION = 'APPROVED_CORRECTION'
    ALL = (CHECK_IN, CHECK_OUT, APPROVED_CORRECTION)


class VisitEvent(db.Model):
    __tablename__ = 'visit_events'

    id = db.Column(db.Integer, primary_key=True)
    visit_session_id = db.Column(db.Integer, db.ForeignKey('visit_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    event_type = db.Column(db.String(32), nullable=False, index=True)
    occurred_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    correction_reason = db.Column(db.String(255), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    recorded_by = db.relationship('User', foreign_keys=[recorded_by_id])

    def get_metadata(self) -> dict:
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except Exception:
            return {}

    def set_metadata(self, data: dict):
        self.metadata_json = json.dumps(data) if data else None

    def to_dict(self):
        return {
            'id': self.id,
            'visit_session_id': self.visit_session_id,
            'event_type': self.event_type,
            'occurred_at': self.occurred_at.isoformat() if self.occurred_at else None,
            'recorded_by_id': self.recorded_by_id,
            'recorded_by_name': self.recorded_by.full_name if self.recorded_by else None,
            'correction_reason': self.correction_reason,
            'metadata': self.get_metadata()
        }

    def __repr__(self):
        return f"<VisitEvent id={self.id} session_id={self.visit_session_id} event_type='{self.event_type}'>"
