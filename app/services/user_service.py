from sqlalchemy import or_, text
from app.extensions import db
from app.models.user import User, UserRole
from app.models.audit_log import AuditAction, AuditOutcome
from app.services.audit_service import AuditService


class UserService:
    @staticmethod
    def list_users(role: str | None = None, is_active: bool | None = None, search: str | None = None):
        """Returns filtered list of staff accounts."""
        query = User.query
        if role and role in UserRole.ALL:
            query = query.filter_by(role=role)
        if is_active is not None:
            query = query.filter_by(is_active=is_active)
        if search:
            search_term = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    db.func.lower(User.username).like(search_term),
                    db.func.lower(User.full_name).like(search_term),
                    db.func.lower(User.email).like(search_term),
                    db.func.lower(User.department).like(search_term)
                )
            )
        return query.order_by(User.created_at.desc()).all()

    @staticmethod
    def create_staff_user(
        username: str,
        email: str | None,
        full_name: str,
        role: str,
        department: str | None,
        password: str,
        actor_user: User | None = None
    ) -> tuple[User | None, str | None]:
        """Creates a new staff member account with validation and audit logging."""
        username = (username or '').strip().lower()
        email = (email or '').strip().lower() if email else None
        full_name = (full_name or '').strip()
        department = (department or '').strip() if department else None

        if not username or len(username) < 3:
            return None, "Username must be at least 3 characters long."
        if not full_name:
            return None, "Full name is required."
        if role not in UserRole.ALL:
            return None, f"Invalid role '{role}'. Allowed roles: {', '.join(UserRole.ALL)}."
        if not password or len(password) < 6:
            return None, "Password must be at least 6 characters long."

        # Uniqueness checks
        if User.query.filter(db.func.lower(User.username) == username).first():
            return None, f"Username '{username}' is already in use."
        if email and User.query.filter(db.func.lower(User.email) == email).first():
            return None, f"Email address '{email}' is already in use."

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            role=role,
            department=department,
            is_active=True
        )
        try:
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            AuditService.log_event(
                action=AuditAction.USER_CREATE,
                entity_type='USER',
                outcome=AuditOutcome.SUCCESS,
                actor_user_id=actor_user.id if actor_user else None,
                entity_reference=user.username,
                reason=f"Created staff account with role {role}",
                metadata={'role': role, 'department': department}
            )
            return user, None
        except Exception as e:
            db.session.rollback()
            return None, f"Database error creating user: {str(e)}"

    @staticmethod
    def update_staff_user(
        user_id: int,
        full_name: str,
        email: str | None,
        department: str | None,
        role: str,
        is_active: bool,
        actor_user: User
    ) -> tuple[User | None, str | None]:
        """
        Updates staff account details with concurrency-safe last-admin protection
        and self-demotion/self-deactivation guards.
        """
        # 1. Self-protection checks
        if actor_user.id == user_id:
            if role != UserRole.ADMIN and actor_user.role == UserRole.ADMIN:
                return None, "Administrators cannot demote their own account."
            if not is_active:
                return None, "Administrators cannot deactivate their own account."

        if role not in UserRole.ALL:
            return None, f"Invalid role '{role}'."

        try:
            # Immediate write lock on SQLite to guard against concurrent race conditions
            try:
                db.session.execute(text("BEGIN IMMEDIATE"))
            except Exception:
                pass  # In-memory test db or non-sqlite dialect handles transactions natively

            target_user = db.session.get(User, user_id)
            if not target_user:
                db.session.rollback()
                return None, "Staff account not found."

            # 2. Concurrency-safe Last-Administrator Protection
            if target_user.is_admin and target_user.is_active:
                demoting_or_deactivating = (role != UserRole.ADMIN) or (not is_active)
                if demoting_or_deactivating:
                    active_admins = User.query.filter_by(role=UserRole.ADMIN, is_active=True).count()
                    if active_admins <= 1:
                        db.session.rollback()
                        return None, "Cannot deactivate or demote the last remaining active administrator."

            # Email uniqueness check
            email = (email or '').strip().lower() if email else None
            if email and email != (target_user.email or '').lower():
                existing = User.query.filter(db.func.lower(User.email) == email, User.id != user_id).first()
                if existing:
                    db.session.rollback()
                    return None, f"Email address '{email}' is already taken by another account."

            # Apply changes
            target_user.full_name = full_name.strip()
            target_user.email = email
            target_user.department = department.strip() if department else None
            target_user.role = role
            target_user.is_active = is_active

            db.session.commit()

            AuditService.log_event(
                action=AuditAction.USER_UPDATE if is_active else AuditAction.USER_DEACTIVATE,
                entity_type='USER',
                outcome=AuditOutcome.SUCCESS,
                actor_user_id=actor_user.id,
                entity_reference=target_user.username,
                reason=f"Updated details (active={is_active}, role={role})"
            )
            return target_user, None

        except Exception as e:
            db.session.rollback()
            return None, f"Error updating account: {str(e)}"
