from app.routes.main import main_bp
from app.routes.auth import auth_bp
from app.routes.admin import admin_bp
from app.routes.faculty import faculty_bp
from app.routes.security import security_bp
from app.routes.visitors import visitors_bp
from app.routes.lookup import lookup_bp

__all__ = [
    'main_bp',
    'auth_bp',
    'admin_bp',
    'faculty_bp',
    'security_bp',
    'visitors_bp',
    'lookup_bp',
]
