import uuid
from datetime import datetime, timezone
from app.extensions import db
from app.models.types import UTCDateTime


class Visitor(db.Model):
    __tablename__ = 'visitors'

    id = db.Column(db.Integer, primary_key=True)
    public_reference = db.Column(db.String(32), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    normalized_phone = db.Column(db.String(32), nullable=True, index=True)
    phone = db.Column(db.String(32), nullable=True)
    email = db.Column(db.String(120), nullable=True, index=True)
    organization = db.Column(db.String(120), nullable=True)
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

    # Relationship to visit requests
    visit_requests = db.relationship('VisitRequest', backref='visitor', lazy='dynamic', cascade='all, delete-orphan')

    @classmethod
    def generate_reference(cls) -> str:
        """Generates a unique visitor reference code."""
        return f"VIS-{uuid.uuid4().hex[:8].upper()}"

    def to_dict(self):
        return {
            'id': self.id,
            'public_reference': self.public_reference,
            'full_name': self.full_name,
            'phone': self.phone,
            'email': self.email,
            'organization': self.organization,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<Visitor id={self.id} ref='{self.public_reference}' name='{self.full_name}'>"
