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
    """Seeds default staff accounts for Admin, Faculty, and Security."""
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

        db.create_all()
        from app.services.auth_service import AuthService
        created = AuthService.ensure_default_accounts()
        if created > 0:
            click.echo(click.style(f"Seeded {created} users successfully.", fg="green"))
        else:
            click.echo(click.style("All default accounts already present.", fg="yellow"))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='127.0.0.1', port=port, debug=True)
