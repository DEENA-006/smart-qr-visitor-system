import os
import logging
from datetime import datetime, timezone, timedelta
import zoneinfo
from flask import Flask, render_template, request, has_request_context
from app.config import config_by_name
from app.extensions import db, migrate, login_manager, csrf
from app.routes import main_bp, auth_bp, admin_bp, faculty_bp, security_bp, visitors_bp, lookup_bp


def create_app(config_name: str | None = None) -> Flask:
    """Application factory for Smart QR Visitor Management System."""
    app = Flask(__name__)

    # Determine configuration
    if config_name is None:
        config_name = os.environ.get('APP_ENV', 'development').lower()
    
    config_class = config_by_name.get(config_name, config_by_name['default'])
    app.config.from_object(config_class)

    # Configure logging
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(faculty_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(visitors_bp)
    app.register_blueprint(lookup_bp)

    # Template filters & context processors
    @app.context_processor
    def utility_processor():
        def get_app_timezone():
            tz_name = app.config.get('APP_TIMEZONE', 'Asia/Kolkata')
            try:
                return zoneinfo.ZoneInfo(tz_name)
            except Exception:
                # Guaranteed IST fallback (UTC+05:30) for systems without IANA tzdata
                if tz_name in ('Asia/Kolkata', 'Asia/Calcutta', 'IST'):
                    return timezone(timedelta(hours=5, minutes=30), name='IST')
                return timezone.utc

        def format_dt(dt, fmt='%d %b %Y, %I:%M %p'):
            """Formats UTC datetime into configured local timezone (defaults to Asia/Kolkata / IST)."""
            if not dt:
                return '—'
            try:
                target_tz = get_app_timezone()
                if dt.tzinfo is None:
                    # Treat naive as UTC
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(target_tz)
                return local_dt.strftime(fmt)
            except Exception:
                return dt.strftime(fmt)

        def to_local_input_dt(dt):
            """Converts UTC datetime to local YYYY-MM-DDTHH:MM string for input[type=datetime-local]."""
            if not dt:
                return ''
            try:
                target_tz = get_app_timezone()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(target_tz)
                return local_dt.strftime('%Y-%m-%dT%H:%M')
            except Exception:
                return dt.strftime('%Y-%m-%dT%H:%M')

        def public_form_url(form, external=True):
            """Returns canonical public shareable URL for a published form."""
            if hasattr(form, 'get_public_url'):
                return form.get_public_url(external=external)
            token = getattr(form, 'public_token', None) or getattr(form, 'visit_type', 'GENERAL')
            path = f"/register/{token}"
            base_url = (app.config.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')
            if base_url:
                if not base_url.startswith(('http://', 'https://')):
                    base_url = f"https://{base_url}"
                return f"{base_url}{path}"
            if has_request_context():
                return request.host_url.rstrip('/') + path
            return f"http://localhost:5000{path}"

        return {
            'now': datetime.now(timezone.utc),
            'app_name': 'Smart Visitor',
            'full_app_name': 'Smart QR Visitor Management System',
            'app_tagline': 'Secure Entry. Smarter Access.',
            'format_dt': format_dt,
            'to_local_input_dt': to_local_input_dt,
            'public_form_url': public_form_url
        }

    # Error Handlers
    @app.errorhandler(429)
    def ratelimit_error(error):
        retry_after = getattr(error, 'description', None)
        return render_template('errors/429.html', retry_after=retry_after), 429

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    return app
