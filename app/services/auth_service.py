import os
from datetime import datetime, timezone
from functools import wraps
from flask import request, redirect, url_for, flash, abort
from flask_login import current_user, login_user, logout_user
from app.extensions import db
from app.models.user import User, UserRole
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.audit_service import AuditService


class AuthService:
    @classmethod
    def ensure_default_accounts(cls) -> int:
        """
        Ensures default staff accounts exist (Admin, Faculty, Security).
        Creates them if missing. Idempotent and safe across multi-instance cold starts.
        """
        seeded_accounts = [
            {
                'username': 'admin',
                'email': 'admin@campus.edu',
                'full_name': 'Campus Administrator',
                'role': UserRole.ADMIN,
                'password': os.environ.get('DEFAULT_ADMIN_PASSWORD', 'Admin@123'),
                'department': 'Administration'
            },
            {
                'username': 'faculty',
                'email': 'faculty@campus.edu',
                'full_name': 'Dr. Sarah Jenkins',
                'role': UserRole.FACULTY,
                'password': os.environ.get('DEFAULT_FACULTY_PASSWORD', 'Faculty@123'),
                'department': 'Computer Science & Engineering'
            },
            {
                'username': 'security',
                'email': 'security@campus.edu',
                'full_name': 'Officer Marcus Reed',
                'role': UserRole.SECURITY,
                'password': os.environ.get('DEFAULT_SECURITY_PASSWORD', 'Security@123'),
                'department': 'Main Campus Security Desk'
            }
        ]

        created_count = 0
        for acc in seeded_accounts:
            existing = User.query.filter(
                (db.func.lower(User.username) == acc['username'].lower()) |
                (db.func.lower(User.email) == acc['email'].lower())
            ).first()
            if not existing:
                user = User(
                    username=acc['username'],
                    email=acc['email'],
                    full_name=acc['full_name'],
                    role=acc['role'],
                    department=acc['department'],
                    is_active=True
                )
                user.set_password(acc['password'])
                db.session.add(user)
                created_count += 1

        if created_count > 0:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        return created_count

    @classmethod
    def authenticate_user(cls, identifier: str, password: str) -> tuple[User | None, str | None]:
        """
        Validates credentials and logs in the user.
        Accepts username or email.
        Returns (user, None) on success or (None, error_message) on failure.
        """
        if not identifier or not password:
            return None, "Please provide both username/email and password."

        identifier = identifier.strip().lower()
        user = User.query.filter(
            (db.func.lower(User.username) == identifier) | 
            (db.func.lower(User.email) == identifier)
        ).first()

        # Self-healing fallback: If user was not found, check if default accounts need provisioning
        if not user:
            default_identifiers = (
                'admin', 'admin@campus.edu',
                'faculty', 'faculty@campus.edu',
                'security', 'security@campus.edu'
            )
            if identifier in default_identifiers or User.query.first() is None:
                cls.ensure_default_accounts()
                user = User.query.filter(
                    (db.func.lower(User.username) == identifier) | 
                    (db.func.lower(User.email) == identifier)
                ).first()

        ip = request.remote_addr if request else None
        ua = str(request.user_agent.string)[:255] if request and request.user_agent else None

        if not user:
            AuditService.log_event(
                action=AuditAction.LOGIN_FAILURE,
                entity_type='USER',
                outcome=AuditOutcome.FAILURE,
                reason="Invalid credentials: username/email not found",
                metadata={'submitted_identifier': identifier},
                ip_address=ip,
                user_agent=ua
            )
            return None, "Invalid username/email or password."

        if not user.is_active:
            AuditService.log_event(
                action=AuditAction.LOGIN_FAILURE,
                entity_type='USER',
                outcome=AuditOutcome.FAILURE,
                actor_user_id=user.id,
                entity_reference=user.username,
                reason="Account is deactivated",
                ip_address=ip,
                user_agent=ua
            )
            return None, "This account is inactive. Please contact your system administrator."

        if not user.check_password(password):
            AuditService.log_event(
                action=AuditAction.LOGIN_FAILURE,
                entity_type='USER',
                outcome=AuditOutcome.FAILURE,
                actor_user_id=user.id,
                entity_reference=user.username,
                reason="Invalid password",
                ip_address=ip,
                user_agent=ua
            )
            return None, "Invalid username/email or password."

        # Successful authentication
        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()

        login_user(user, remember=False)

        AuditService.log_event(
            action=AuditAction.LOGIN_SUCCESS,
            entity_type='USER',
            outcome=AuditOutcome.SUCCESS,
            actor_user_id=user.id,
            entity_reference=user.username,
            reason="User authenticated successfully",
            ip_address=ip,
            user_agent=ua
        )

        return user, None

    @staticmethod
    def logout_current_user():
        """Logs out current user and creates audit log."""
        if current_user.is_authenticated:
            user_id = current_user.id
            username = current_user.username
            ip = request.remote_addr if request else None
            ua = str(request.user_agent.string)[:255] if request and request.user_agent else None

            AuditService.log_event(
                action=AuditAction.LOGOUT,
                entity_type='USER',
                outcome=AuditOutcome.SUCCESS,
                actor_user_id=user_id,
                entity_reference=username,
                reason="User initiated logout",
                ip_address=ip,
                user_agent=ua
            )
            logout_user()

    @staticmethod
    def get_dashboard_endpoint(user: User) -> str:
        """Determines default landing dashboard for a given user role."""
        if user.role == UserRole.ADMIN:
            return 'admin.dashboard'
        elif user.role == UserRole.FACULTY:
            return 'faculty.dashboard'
        elif user.role == UserRole.SECURITY:
            return 'security.dashboard'
        return 'main.index'


def role_required(*allowed_roles: str):
    """
    Decorator to enforce server-side role-based authorization.
    Requires user to be logged in and possess one of the allowed roles.
    Returns 403 Forbidden with security logging if role condition is violated.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this resource.", "warning")
                return redirect(url_for('auth.login', next=request.url))

            if not current_user.has_role(*allowed_roles):
                ip = request.remote_addr if request else None
                ua = str(request.user_agent.string)[:255] if request and request.user_agent else None
                AuditService.log_event(
                    action=AuditAction.UNAUTHORIZED_ACCESS,
                    entity_type='ROUTE',
                    outcome=AuditOutcome.FAILURE,
                    actor_user_id=current_user.id,
                    entity_reference=request.path,
                    reason=f"Role {current_user.role} attempted to access route restricted to {allowed_roles}",
                    ip_address=ip,
                    user_agent=ua
                )
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
