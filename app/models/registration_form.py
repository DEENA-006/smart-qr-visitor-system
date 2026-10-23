import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.types import UTCDateTime


class FormVersionStatus:
    DRAFT = 'DRAFT'
    PUBLISHED = 'PUBLISHED'
    ARCHIVED = 'ARCHIVED'

    ALL = (DRAFT, PUBLISHED, ARCHIVED)


class RegistrationForm(db.Model):
    __tablename__ = 'registration_forms'

    id = db.Column(db.Integer, primary_key=True)
    public_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    visit_type = db.Column(db.String(32), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    allow_faculty_customization = db.Column(db.Boolean, default=False, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
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
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    versions = db.relationship(
        'FormVersion',
        backref='form',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='FormVersion.version_number.desc()'
    )

    @property
    def published_version(self):
        """Returns the currently active published version, if any."""
        return self.versions.filter_by(status=FormVersionStatus.PUBLISHED).first()

    @classmethod
    def generate_public_token(cls, visit_type: str = 'GENERAL') -> str:
        import secrets
        vt = (visit_type or 'GENERAL').upper().strip()
        return f"FORM-{vt}-{secrets.token_urlsafe(8)}"

    def get_public_token(self) -> str:
        if not self.public_token:
            self.public_token = self.generate_public_token(self.visit_type)
        return self.public_token

    def get_public_url(self, external: bool = True) -> str:
        """
        Generates canonical public registration URL for this form.
        - Prioritizes canonical production domain: https://smart-qr-visitor-system.vercel.app.
        - In production, enforces HTTPS and verified canonical host (strictly rejects rogue or misconfigured test URLs like Smart_QR_tracking).
        - In local development without configured base, falls back to request host or http://localhost:5000.
        - Generates the unique public unauthenticated URL: /register/<public_token>.
        """
        import os
        from flask import current_app, has_request_context, request, url_for

        token = self.get_public_token() if hasattr(self, 'get_public_token') else (self.public_token or self.visit_type or 'GENERAL')

        path = f"/register/{token}"
        if has_request_context():
            try:
                path = url_for('visitors.register_form', visit_type=token, _external=False)
            except Exception:
                path = f"/register/{token}"

        if not external:
            return path

        def _is_safe_canonical_base(url: str) -> bool:
            if not url:
                return False
            u = url.strip().lower()
            if 'smart_qr_tracking' in u or 'smart-qr-tracking' in u:
                return False
            # Reject hostnames with invalid characters like underscores (RFC 1123 violation that breaks SSL certs)
            host_part = u.split('://')[-1].split('/')[0].split(':')[0]
            if '_' in host_part or not host_part:
                return False
            return True

        base_url = ""
        is_prod = False

        if current_app:
            raw_app_base = (current_app.config.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')
            if _is_safe_canonical_base(raw_app_base):
                base_url = raw_app_base
            env = (current_app.config.get('ENV') or '').lower()
            is_prod = (
                env == 'production' or 
                (current_app.config.get('TESTING') is False and not current_app.config.get('DEBUG', True))
            )

        if not base_url:
            raw_env_base = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
            if _is_safe_canonical_base(raw_env_base):
                base_url = raw_env_base

        # Check environment variable overrides for production
        env_mode = (os.environ.get('FLASK_ENV') or os.environ.get('APP_ENV') or '').lower()
        if env_mode == 'production' or os.environ.get('VERCEL') == '1':
            is_prod = True

        # Automatic detection of Vercel production domain
        if not base_url:
            vercel_prod = os.environ.get('VERCEL_PROJECT_PRODUCTION_URL')
            vercel_url = os.environ.get('VERCEL_URL')
            if vercel_prod and _is_safe_canonical_base(vercel_prod):
                base_url = f"https://{vercel_prod.strip().rstrip('/')}"
            elif vercel_url and _is_safe_canonical_base(vercel_url):
                base_url = f"https://{vercel_url.strip().rstrip('/')}"

        # If inside a live request context:
        if has_request_context():
            req_host = request.host
            # If the user is browsing on smart-qr-visitor-system.vercel.app, ALWAYS use canonical domain
            if req_host and 'smart-qr-visitor-system' in req_host.lower():
                return f"https://smart-qr-visitor-system.vercel.app{path}"

            # If request is on a production cloud host (e.g. *.vercel.app or custom domain)
            if req_host and not any(lh in req_host for lh in ('localhost', '127.0.0.1', '0.0.0.0')):
                if not base_url or 'localhost' in base_url or '127.0.0.1' in base_url:
                    scheme = 'https' if (request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https' or is_prod) else request.scheme
                    return f"{scheme}://{req_host}{path}"

        if is_prod:
            # Enforce HTTPS and canonical domain in production
            if base_url:
                if not base_url.startswith(('http://', 'https://')):
                    base_url = f"https://{base_url}"
                elif base_url.startswith('http://'):
                    base_url = f"https://{base_url[7:]}"
                # Never generate localhost or 127.0.0.1 in production
                if not any(lh in base_url for lh in ('localhost', '127.0.0.1', '0.0.0.0')):
                    return f"{base_url}{path}"

            # Fallback in production from live request context if valid public host
            if has_request_context():
                host = request.host
                if host and not any(lh in host for lh in ('localhost', '127.0.0.1', '0.0.0.0')):
                    return f"https://{host}{path}"

            # Fallback to configured Vercel production canonical deployment
            return f"https://smart-qr-visitor-system.vercel.app{path}"

        # Development / Testing mode:
        if base_url:
            if not base_url.startswith(('http://', 'https://')):
                base_url = f"https://{base_url}"
            return f"{base_url}{path}"

        if has_request_context():
            return f"{request.host_url.rstrip('/')}{path}"

        return f"http://localhost:5000{path}"

    def to_dict(self):
        pub_ver = self.published_version
        return {
            'id': self.id,
            'public_token': self.public_token,
            'public_url': self.get_public_url(),
            'name': self.name,
            'visit_type': self.visit_type,
            'description': self.description,
            'is_active': self.is_active,
            'allow_faculty_customization': self.allow_faculty_customization,
            'created_by': self.created_by.full_name if self.created_by else None,
            'published_version': pub_ver.version_number if pub_ver else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<RegistrationForm id={self.id} name='{self.name}' type='{self.visit_type}'>"


class FormVersion(db.Model):
    __tablename__ = 'form_versions'

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('registration_forms.id', ondelete='CASCADE'), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=FormVersionStatus.DRAFT, index=True)
    schema_json = db.Column(db.Text, nullable=False, default='[]')
    faculty_permitted_fields_json = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    published_at = db.Column(UTCDateTime, nullable=True)
    created_at = db.Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.UniqueConstraint('form_id', 'version_number', name='uq_form_version_number'),
        # Enforce exactly one active PUBLISHED version per form at database engine level
        db.Index(
            'uq_form_versions_single_published',
            'form_id',
            unique=True,
            sqlite_where=(db.column('status') == FormVersionStatus.PUBLISHED),
            postgresql_where=(db.column('status') == FormVersionStatus.PUBLISHED)
        ),
    )

    def get_schema(self) -> list:
        if not self.schema_json:
            return []
        try:
            return json.loads(self.schema_json)
        except Exception:
            return []

    def set_schema(self, schema_data: list):
        self.schema_json = json.dumps(schema_data)

    def get_faculty_permissions(self) -> dict:
        if not self.faculty_permitted_fields_json:
            return {}
        try:
            return json.loads(self.faculty_permitted_fields_json)
        except Exception:
            return {}

    def set_faculty_permissions(self, perms_dict: dict):
        self.faculty_permitted_fields_json = json.dumps(perms_dict) if perms_dict else None

    @property
    def is_published(self) -> bool:
        return self.status == FormVersionStatus.PUBLISHED

    @property
    def is_draft(self) -> bool:
        return self.status == FormVersionStatus.DRAFT

    @property
    def is_archived(self) -> bool:
        return self.status == FormVersionStatus.ARCHIVED

    def to_dict(self):
        return {
            'id': self.id,
            'form_id': self.form_id,
            'version_number': self.version_number,
            'status': self.status,
            'schema': self.get_schema(),
            'faculty_permissions': self.get_faculty_permissions(),
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<FormVersion id={self.id} form_id={self.form_id} v={self.version_number} status='{self.status}'>"
