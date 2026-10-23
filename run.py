import os
import click
from app import create_app
from app.extensions import db
from app.models.user import User, UserRole
from app.services.audit_service import AuditService
from app.models.audit_log import AuditAction, AuditOutcome

app = create_app()


@app.cli.command("init-db")
def init_db():
    """Initializes the database schema."""
    with app.app_context():
        db.create_all()
        click.echo(click.style("Database tables initialized successfully.", fg="green"))


@app.cli.command("seed-users")
def seed_users():
    """Seeds default development staff accounts for Admin, Faculty, and Security."""
    with app.app_context():
        # Validate effective application configuration to fail safely
        env = os.environ.get('APP_ENV', '').strip().lower()
        is_safe_dev = (
            (env in ('development', 'dev') and app.config.get('DEBUG') is True)
            or app.config.get('TESTING', False)
        )

        if not is_safe_dev:
            click.echo(
                click.style(
                    "SECURITY REFUSAL: 'seed-users' is restricted to local development environments.\n"
                    f"Refusing execution because APP_ENV='{env}' or DEBUG is not enabled.",
                    fg="red",
                    bold=True
                )
            )
            return

        # Ensure tables exist
        db.create_all()

        seeded_accounts = [
            {
                'username': 'admin',
                'email': 'admin@campus.edu',
                'full_name': 'Campus Administrator',
                'role': UserRole.ADMIN,
                'password': 'Admin@123',
                'department': 'Administration'
            },
            {
                'username': 'faculty',
                'email': 'faculty@campus.edu',
                'full_name': 'Dr. Sarah Jenkins',
                'role': UserRole.FACULTY,
                'password': 'Faculty@123',
                'department': 'Computer Science & Engineering'
            },
            {
                'username': 'security',
                'email': 'security@campus.edu',
                'full_name': 'Officer Marcus Reed',
                'role': UserRole.SECURITY,
                'password': 'Security@123',
                'department': 'Main Campus Security Desk'
            }
        ]

        created_count = 0
        for acc in seeded_accounts:
            existing = User.query.filter_by(username=acc['username']).first()
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
                click.echo(f"Created {acc['role']} user: {acc['username']} (Password: {acc['password']})")
            else:
                click.echo(f"User '{acc['username']}' already exists, skipping.")

        if created_count > 0:
            db.session.commit()
            AuditService.log_event(
                action=AuditAction.USER_CREATE,
                entity_type='USER',
                outcome=AuditOutcome.SUCCESS,
                reason="Development seed accounts populated"
            )
            click.echo(click.style(f"Seeded {created_count} users successfully.", fg="green"))
        else:
            click.echo(click.style("All default accounts already present.", fg="yellow"))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='127.0.0.1', port=port, debug=True)
